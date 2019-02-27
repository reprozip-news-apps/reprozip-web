
'Frame Manager module.'
import asyncio
from collections import OrderedDict
import logging
from types import SimpleNamespace
from typing import Any, Awaitable, Dict, Generator, List, Optional, Union
from typing import TYPE_CHECKING
from pyee import EventEmitter
from pyppeteer import helper
from pyppeteer.connection import CDPSession
from pyppeteer.element_handle import ElementHandle
from pyppeteer.errors import NetworkError
from pyppeteer.execution_context import ExecutionContext, JSHandle
from pyppeteer.errors import ElementHandleError, PageError, TimeoutError
from pyppeteer.util import merge_dict
if TYPE_CHECKING:
    from typing import Set
logger = logging.getLogger(__name__)


class FrameManager(EventEmitter):
    'FrameManager class.'
    Events = SimpleNamespace(FrameAttached='frameattached', FrameNavigated='framenavigated', FrameDetached='framedetached',
                             LifecycleEvent='lifecycleevent', FrameNavigatedWithinDocument='framenavigatedwithindocument')

    def __init__(self, client: CDPSession, frameTree: Dict, page: Any) -> None:
        'Make new frame manager.'
        super().__init__()
        self._client = client
        self._page = page
        self._frames = OrderedDict()
        self._mainFrame = None
        self._contextIdToContext = dict()
        client.on('Page.frameAttached', (lambda event: self._onFrameAttached(
            event.get('frameId', ''), event.get('parentFrameId', ''))))
        client.on('Page.frameNavigated',
                  (lambda event: self._onFrameNavigated(event.get('frame'))))
        client.on('Page.navigatedWithinDocument', (lambda event: self._onFrameNavigatedWithinDocument(
            event.get('frameId'), event.get('url'))))
        client.on('Page.frameDetached',
                  (lambda event: self._onFrameDetached(event.get('frameId'))))
        client.on('Page.frameStoppedLoading',
                  (lambda event: self._onFrameStoppedLoading(event.get('frameId'))))
        client.on('Runtime.executionContextCreated',
                  (lambda event: self._onExecutionContextCreated(event.get('context'))))
        client.on('Runtime.executionContextDestroyed',
                  (lambda event: self._onExecutionContextDestroyed(event.get('executionContextId'))))
        client.on('Runtime.executionContextsCleared',
                  (lambda event: self._onExecutionContextsCleared()))
        client.on('Page.lifecycleEvent',
                  (lambda event: self._onLifecycleEvent(event)))
        self._handleFrameTree(frameTree)

    def _onLifecycleEvent(self, event: Dict) -> None:
        frame = self._frames.get(event['frameId'])
        if (not frame):
            return
        frame._onLifecycleEvent(event['loaderId'], event['name'])
        self.emit(FrameManager.Events.LifecycleEvent, frame)

    def _onFrameStoppedLoading(self, frameId: str) -> None:
        frame = self._frames.get(frameId)
        if (not frame):
            return
        frame._onLoadingStopped()
        self.emit(FrameManager.Events.LifecycleEvent, frame)

    def _handleFrameTree(self, frameTree: Dict) -> None:
        frame = frameTree['frame']
        if ('parentId' in frame):
            self._onFrameAttached(frame['id'], frame['parentId'])
        self._onFrameNavigated(frame)
        if ('childFrames' not in frameTree):
            return
        for child in frameTree['childFrames']:
            self._handleFrameTree(child)

    @property
    def mainFrame(self) -> Optional['Frame']:
        'Return main frame.'
        return self._mainFrame

    def frames(self) -> List['Frame']:
        'Return all frames.'
        return list(self._frames.values())

    def frame(self, frameId: str) -> Optional['Frame']:
        'Return :class:`Frame` of ``frameId``.'
        return self._frames.get(frameId)

    def _onFrameAttached(self, frameId: str, parentFrameId: str) -> None:
        if (frameId in self._frames):
            return
        parentFrame = self._frames.get(parentFrameId)
        frame = Frame(self._client, parentFrame, frameId)
        self._frames[frameId] = frame
        self.emit(FrameManager.Events.FrameAttached, frame)

    def _onFrameNavigated(self, framePayload: dict) -> None:
        isMainFrame = (not framePayload.get('parentId'))
        if isMainFrame:
            frame = self._mainFrame
        else:
            frame = self._frames.get(framePayload.get('id', ''))
        if (not (isMainFrame or frame)):
            raise PageError(
                'We either navigate top level or have old version of the navigated frame')
        if frame:
            for child in frame.childFrames:
                self._removeFramesRecursively(child)
        _id = framePayload.get('id', '')
        if isMainFrame:
            if frame:
                self._frames.pop(frame._id, None)
                frame._id = _id
            else:
                frame = Frame(self._client, None, _id)
            self._frames[_id] = frame
            self._mainFrame = frame
        frame._navigated(framePayload)
        self.emit(FrameManager.Events.FrameNavigated, frame)

    def _onFrameNavigatedWithinDocument(self, frameId: str, url: str) -> None:
        frame = self._frames.get(frameId)
        if (not frame):
            return
        frame._navigatedWithinDocument(url)
        self.emit(FrameManager.Events.FrameNavigatedWithinDocument, frame)
        self.emit(FrameManager.Events.FrameNavigated, frame)

    def _onFrameDetached(self, frameId: str) -> None:
        frame = self._frames.get(frameId)
        if frame:
            self._removeFramesRecursively(frame)

    def _onExecutionContextCreated(self, contextPayload: Dict) -> None:
        if (contextPayload.get('auxData') and contextPayload['auxData']['isDefault']):
            frameId = contextPayload['auxData']['frameId']
        else:
            frameId = None
        frame = (self._frames.get(frameId) if frameId else None)
        context = ExecutionContext(self._client, contextPayload, (
            lambda obj: self.createJSHandle(contextPayload['id'], obj)), frame)
        self._contextIdToContext[contextPayload['id']] = context
        if frame:
            frame._setDefaultContext(context)

    def _removeContext(self, context: ExecutionContext) -> None:
        frame = (self._frames[context._frameId] if context._frameId else None)
        if (frame and context._isDefault):
            frame._setDefaultContext(None)

    def _onExecutionContextDestroyed(self, executionContextId: str) -> None:
        context = self._contextIdToContext.get(executionContextId)
        if (not context):
            return
        del self._contextIdToContext[executionContextId]
        self._removeContext(context)

    def _onExecutionContextsCleared(self) -> None:
        for context in self._contextIdToContext.values():
            self._removeContext(context)
        self._contextIdToContext.clear()

    def createJSHandle(self, contextId: str, remoteObject: Dict = None) -> JSHandle:
        'Create JS handle associated to the context id and remote object.'
        if (remoteObject is None):
            remoteObject = dict()
        context = self._contextIdToContext.get(contextId)
        if (not context):
            raise ElementHandleError(
                ''.join(['missing context with id = ', '{}'.format(contextId)]))
        if (remoteObject.get('subtype') == 'node'):
            return ElementHandle(context, self._client, remoteObject, self._page, self)
        return JSHandle(context, self._client, remoteObject)

    def _removeFramesRecursively(self, frame: 'Frame') -> None:
        for child in frame.childFrames:
            self._removeFramesRecursively(child)
        frame._detach()
        self._frames.pop(frame._id, None)
        self.emit(FrameManager.Events.FrameDetached, frame)


class Frame(object):
    'Frame class.\n\n    Frame objects can be obtained via :attr:`pyppeteer.page.Page.mainFrame`.\n    '

    def __init__(self, client: CDPSession, parentFrame: Optional['Frame'], frameId: str) -> None:
        self._client = client
        self._parentFrame = parentFrame
        self._url = ''
        self._detached = False
        self._id = frameId
        self._documentPromise = None
        self._contextResolveCallback = (lambda _: None)
        self._setDefaultContext(None)
        self._waitTasks = set()
        self._loaderId = ''
        self._lifecycleEvents = set()
        self._childFrames = set()
        if self._parentFrame:
            self._parentFrame._childFrames.add(self)

    def _setDefaultContext(self, context: Optional[ExecutionContext]) -> None:
        if (context is not None):
            self._contextResolveCallback(context)
            self._contextResolveCallback = (lambda _: None)
            for waitTask in self._waitTasks:
                self._client._loop.create_task(waitTask.rerun())
        else:
            self._documentPromise = None
            self._contextPromise = self._client._loop.create_future()
            self._contextResolveCallback = (
                lambda _context: self._contextPromise.set_result(_context))

    async def executionContext(self) -> Optional[ExecutionContext]:
        'Return execution context of this frame.\n\n        Return :class:`~pyppeteer.execution_context.ExecutionContext`\n        associated to this frame.\n        '
        return (await self._contextPromise)

    async def evaluateHandle(self, pageFunction: str, *args: Any) -> JSHandle:
        'Execute function on this frame.\n\n        Details see :meth:`pyppeteer.page.Page.evaluateHandle`.\n        '
        context = (await self.executionContext())
        if (context is None):
            raise PageError('this frame has no context.')
        return (await context.evaluateHandle(pageFunction, *args))

    async def evaluate(self, pageFunction: str, *args: Any, force_expr: bool = False) -> Any:
        'Evaluate pageFunction on this frame.\n\n        Details see :meth:`pyppeteer.page.Page.evaluate`.\n        '
        context = (await self.executionContext())
        if (context is None):
            raise ElementHandleError('ExecutionContext is None.')
        return (await context.evaluate(pageFunction, *args, force_expr=force_expr))

    async def querySelector(self, selector: str) -> Optional[ElementHandle]:
        'Get element which matches `selector` string.\n\n        Details see :meth:`pyppeteer.page.Page.querySelector`.\n        '
        document = (await self._document())
        value = (await document.querySelector(selector))
        return value

    async def _document(self) -> ElementHandle:
        if self._documentPromise:
            return self._documentPromise
        context = (await self.executionContext())
        if (context is None):
            raise PageError('No context exists.')
        document = (await context.evaluateHandle('document')).asElement()
        self._documentPromise = document
        if (document is None):
            raise PageError('Could not find `document`.')
        return document

    async def xpath(self, expression: str) -> List[ElementHandle]:
        'Evaluate the XPath expression.\n\n        If there are no such elements in this frame, return an empty list.\n\n        :arg str expression: XPath string to be evaluated.\n        '
        document = (await self._document())
        value = (await document.xpath(expression))
        return value

    async def querySelectorEval(self, selector: str, pageFunction: str, *args: Any) -> Any:
        'Execute function on element which matches selector.\n\n        Details see :meth:`pyppeteer.page.Page.querySelectorEval`.\n        '
        document = (await self._document())
        return (await document.querySelectorEval(selector, pageFunction, *args))

    async def querySelectorAllEval(self, selector: str, pageFunction: str, *args: Any) -> Optional[Dict]:
        'Execute function on all elements which matches selector.\n\n        Details see :meth:`pyppeteer.page.Page.querySelectorAllEval`.\n        '
        document = (await self._document())
        value = (await document.JJeval(selector, pageFunction, *args))
        return value

    async def querySelectorAll(self, selector: str) -> List[ElementHandle]:
        'Get all elements which matches `selector`.\n\n        Details see :meth:`pyppeteer.page.Page.querySelectorAll`.\n        '
        document = (await self._document())
        value = (await document.querySelectorAll(selector))
        return value
    J = querySelector
    Jx = xpath
    Jeval = querySelectorEval
    JJ = querySelectorAll
    JJeval = querySelectorAllEval

    async def content(self) -> str:
        'Get the whole HTML contents of the page.'
        return (await self.evaluate("\n() => {\n  let retVal = '';\n  if (document.doctype)\n    retVal = new XMLSerializer().serializeToString(document.doctype);\n  if (document.documentElement)\n    retVal += document.documentElement.outerHTML;\n  return retVal;\n}\n        ".strip()))

    async def setContent(self, html: str) -> None:
        'Set content to this page.'
        func = '\nfunction(html) {\n  document.open();\n  document.write(html);\n  document.close();\n}\n'
        (await self.evaluate(func, html))

    @property
    def name(self) -> str:
        'Get frame name.'
        return self.__dict__.get('_name', '')

    @property
    def url(self) -> str:
        'Get url of the frame.'
        return self._url

    @property
    def parentFrame(self) -> Optional['Frame']:
        'Get parent frame.\n\n        If this frame is main frame or detached frame, return ``None``.\n        '
        return self._parentFrame

    @property
    def childFrames(self) -> List['Frame']:
        'Get child frames.'
        return list(self._childFrames)

    def isDetached(self) -> bool:
        'Return ``True`` if this frame is detached.\n\n        Otherwise return ``False``.\n        '
        return self._detached

    async def injectFile(self, filePath: str) -> str:
        '[Deprecated] Inject file to the frame.'
        logger.warning(
            '`injectFile` method is deprecated. Use `addScriptTag` method instead.')
        with open(filePath) as f:
            contents = f.read()
        contents += '/* # sourceURL= {} */'.format(filePath.replace('\n', ''))
        return (await self.evaluate(contents))

    async def addScriptTag(self, options: Dict) -> ElementHandle:
        'Add script tag to this frame.\n\n        Details see :meth:`pyppeteer.page.Page.addScriptTag`.\n        '
        context = (await self.executionContext())
        if (context is None):
            raise ElementHandleError('ExecutionContext is None.')
        addScriptUrl = "\n        async function addScriptUrl(url, type) {\n            const script = document.createElement('script');\n            script.src = url;\n            if (type)\n                script.type = type;\n            const promise = new Promise((res, rej) => {\n                script.onload = res;\n                script.onerror = rej;\n            });\n            document.head.appendChild(script);\n            await promise;\n            return script;\n        }"
        addScriptContent = "\n        function addScriptContent(content, type = 'text/javascript') {\n            const script = document.createElement('script');\n            script.type = type;\n            script.text = content;\n            let error = null;\n            script.onerror = e => error = e;\n            document.head.appendChild(script);\n            if (error)\n                throw error;\n            return script;\n        }"
        if isinstance(options.get('url'), str):
            url = options['url']
            args = [addScriptUrl, url]
            if ('type' in options):
                args.append(options['type'])
            try:
                return (await context.evaluateHandle(*args)).asElement()
            except ElementHandleError as e:
                raise PageError(
                    ''.join(['Loading script from ', '{}'.format(url), ' failed'])) from e
        if isinstance(options.get('path'), str):
            with open(options['path']) as f:
                contents = f.read()
            contents = (
                contents + '//# sourceURL={}'.format(options['path'].replace('\n', '')))
            args = [addScriptContent, contents]
            if ('type' in options):
                args.append(options['type'])
            return (await context.evaluateHandle(*args)).asElement()
        if isinstance(options.get('content'), str):
            args = [addScriptContent, options['content']]
            if ('type' in options):
                args.append(options['type'])
            return (await context.evaluateHandle(*args)).asElement()
        raise ValueError(
            'Provide an object with a `url`, `path` or `content` property')

    async def addStyleTag(self, options: Dict) -> ElementHandle:
        'Add style tag to this frame.\n\n        Details see :meth:`pyppeteer.page.Page.addStyleTag`.\n        '
        context = (await self.executionContext())
        if (context is None):
            raise ElementHandleError('ExecutionContext is None.')
        addStyleUrl = "\n        async function (url) {\n            const link = document.createElement('link');\n            link.rel = 'stylesheet';\n            link.href = url;\n            const promise = new Promise((res, rej) => {\n                link.onload = res;\n                link.onerror = rej;\n            });\n            document.head.appendChild(link);\n            await promise;\n            return link;\n        }"
        addStyleContent = "\n        async function (content) {\n            const style = document.createElement('style');\n            style.type = 'text/css';\n            style.appendChild(document.createTextNode(content));\n            const promise = new Promise((res, rej) => {\n                style.onload = res;\n                style.onerror = rej;\n            });\n            document.head.appendChild(style);\n            await promise;\n            return style;\n        }"
        if isinstance(options.get('url'), str):
            url = options['url']
            try:
                return (await context.evaluateHandle(addStyleUrl, url)).asElement()
            except ElementHandleError as e:
                raise PageError(
                    ''.join(['Loading style from ', '{}'.format(url), ' failed'])) from e
        if isinstance(options.get('path'), str):
            with open(options['path']) as f:
                contents = f.read()
            contents = (
                contents + '/*# sourceURL={}*/'.format(options['path'].replace('\n', '')))
            return (await context.evaluateHandle(addStyleContent, contents)).asElement()
        if isinstance(options.get('content'), str):
            return (await context.evaluateHandle(addStyleContent, options['content'])).asElement()
        raise ValueError(
            'Provide an object with a `url`, `path` or `content` property')

    async def click(self, selector: str, options: dict = None, **kwargs: Any) -> None:
        'Click element which matches ``selector``.\n\n        Details see :meth:`pyppeteer.page.Page.click`.\n        '
        options = merge_dict(options, kwargs)
        handle = (await self.J(selector))
        if (not handle):
            raise PageError(('No node found for selector: ' + selector))
        (await handle.click(options))
        (await handle.dispose())

    async def focus(self, selector: str) -> None:
        'Focus element which matches ``selector``.\n\n        Details see :meth:`pyppeteer.page.Page.focus`.\n        '
        handle = (await self.J(selector))
        if (not handle):
            raise PageError(('No node found for selector: ' + selector))
        (await self.evaluate('element => element.focus()', handle))
        (await handle.dispose())

    async def hover(self, selector: str) -> None:
        'Mouse hover the element which matches ``selector``.\n\n        Details see :meth:`pyppeteer.page.Page.hover`.\n        '
        handle = (await self.J(selector))
        if (not handle):
            raise PageError(('No node found for selector: ' + selector))
        (await handle.hover())
        (await handle.dispose())

    async def select(self, selector: str, *values: str) -> List[str]:
        'Select options and return selected values.\n\n        Details see :meth:`pyppeteer.page.Page.select`.\n        '
        for value in values:
            if (not isinstance(value, str)):
                raise TypeError(''.join(['Values must be string. Found ', '{}'.format(
                    value), ' of type ', '{}'.format(type(value))]))
        return (await self.querySelectorEval(selector, "\n(element, values) => {\n    if (element.nodeName.toLowerCase() !== 'select')\n        throw new Error('Element is not a <select> element.');\n\n    const options = Array.from(element.options);\n    element.value = undefined;\n    for (const option of options) {\n        option.selected = values.includes(option.value);\n        if (option.selected && !element.multiple)\n            break;\n    }\n\n    element.dispatchEvent(new Event('input', { 'bubbles': true }));\n    element.dispatchEvent(new Event('change', { 'bubbles': true }));\n    return options.filter(option => option.selected).map(options => options.value)\n}\n        ", values))

    async def tap(self, selector: str) -> None:
        'Tap the element which matches the ``selector``.\n\n        Details see :meth:`pyppeteer.page.Page.tap`.\n        '
        handle = (await self.J(selector))
        if (not handle):
            raise PageError(('No node found for selector: ' + selector))
        (await handle.tap())
        (await handle.dispose())

    async def type(self, selector: str, text: str, options: dict = None, **kwargs: Any) -> None:
        'Type ``text`` on the element which matches ``selector``.\n\n        Details see :meth:`pyppeteer.page.Page.type`.\n        '
        options = merge_dict(options, kwargs)
        handle = (await self.querySelector(selector))
        if (handle is None):
            raise PageError('Cannot find {} on this page'.format(selector))
        (await handle.type(text, options))
        (await handle.dispose())

    def waitFor(self, selectorOrFunctionOrTimeout: Union[(str, int, float)], options: dict = None, *args: Any, **kwargs: Any) -> Union[(Awaitable, 'WaitTask')]:
        'Wait until `selectorOrFunctionOrTimeout`.\n\n        Details see :meth:`pyppeteer.page.Page.waitFor`.\n        '
        options = merge_dict(options, kwargs)
        if isinstance(selectorOrFunctionOrTimeout, (int, float)):
            fut = self._client._loop.create_task(
                asyncio.sleep((selectorOrFunctionOrTimeout / 1000)))
            return fut
        if (not isinstance(selectorOrFunctionOrTimeout, str)):
            fut = self._client._loop.create_future()
            fut.set_exception(TypeError(
                ('Unsupported target type: ' + str(type(selectorOrFunctionOrTimeout)))))
            return fut
        if (args or helper.is_jsfunc(selectorOrFunctionOrTimeout)):
            return self.waitForFunction(selectorOrFunctionOrTimeout, options, *args)
        if selectorOrFunctionOrTimeout.startswith('//'):
            return self.waitForXPath(selectorOrFunctionOrTimeout, options)
        return self.waitForSelector(selectorOrFunctionOrTimeout, options)

    def waitForSelector(self, selector: str, options: dict = None, **kwargs: Any) -> 'WaitTask':
        'Wait until element which matches ``selector`` appears on page.\n\n        Details see :meth:`pyppeteer.page.Page.waitForSelector`.\n        '
        options = merge_dict(options, kwargs)
        return self._waitForSelectorOrXPath(selector, False, options)

    def waitForXPath(self, xpath: str, options: dict = None, **kwargs: Any) -> 'WaitTask':
        'Wait until element which matches ``xpath`` appears on page.\n\n        Details see :meth:`pyppeteer.page.Page.waitForXPath`.\n        '
        options = merge_dict(options, kwargs)
        return self._waitForSelectorOrXPath(xpath, True, options)

    def waitForFunction(self, pageFunction: str, options: dict = None, *args: Any, **kwargs: Any) -> 'WaitTask':
        'Wait until the function completes.\n\n        Details see :meth:`pyppeteer.page.Page.waitForFunction`.\n        '
        options = merge_dict(options, kwargs)
        timeout = options.get('timeout', 30000)
        polling = options.get('polling', 'raf')
        return WaitTask(self, pageFunction, 'function', polling, timeout, self._client._loop, *args)

    def _waitForSelectorOrXPath(self, selectorOrXPath: str, isXPath: bool, options: dict = None, **kwargs: Any) -> 'WaitTask':
        options = merge_dict(options, kwargs)
        timeout = options.get('timeout', 30000)
        waitForVisible = bool(options.get('visible'))
        waitForHidden = bool(options.get('hidden'))
        polling = ('raf' if (waitForHidden or waitForVisible) else 'mutation')
        predicate = "\n(selectorOrXPath, isXPath, waitForVisible, waitForHidden) => {\n    const node = isXPath\n        ? document.evaluate(selectorOrXPath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue\n        : document.querySelector(selectorOrXPath);\n    if (!node)\n        return waitForHidden;\n    if (!waitForVisible && !waitForHidden)\n        return node;\n    const element = /** @type {Element} */ (node.nodeType === Node.TEXT_NODE ? node.parentElement : node);\n\n    const style = window.getComputedStyle(element);\n    const isVisible = style && style.visibility !== 'hidden' && hasVisibleBoundingBox();\n    const success = (waitForVisible === isVisible || waitForHidden === !isVisible)\n    return success ? node : null\n\n    function hasVisibleBoundingBox() {\n        const rect = element.getBoundingClientRect();\n        return !!(rect.top || rect.bottom || rect.width || rect.height);\n    }\n}\n        "
        return WaitTask(self, predicate, ''.join(['{}'.format(('XPath' if isXPath else 'selector')), ' "', '{}'.format(selectorOrXPath), '"']), polling, timeout, self._client._loop, selectorOrXPath, isXPath, waitForVisible, waitForHidden)

    async def title(self) -> str:
        'Get title of the frame.'
        return (await self.evaluate('() => document.title'))

    def _navigated(self, framePayload: dict) -> None:
        self._name = framePayload.get('name', '')
        self._navigationURL = framePayload.get('url', '')
        self._url = framePayload.get('url', '')

    def _navigatedWithinDocument(self, url: str) -> None:
        self._url = url

    def _onLifecycleEvent(self, loaderId: str, name: str) -> None:
        if (name == 'init'):
            self._loaderId = loaderId
            self._lifecycleEvents.clear()
        else:
            self._lifecycleEvents.add(name)

    def _onLoadingStopped(self) -> None:
        self._lifecycleEvents.add('DOMContentLoaded')
        self._lifecycleEvents.add('load')

    def _detach(self) -> None:
        for waitTask in self._waitTasks:
            waitTask.terminate(
                PageError('waitForFunction failed: frame got detached.'))
        self._detached = True
        if self._parentFrame:
            self._parentFrame._childFrames.remove(self)
        self._parentFrame = None


class WaitTask(object):
    'WaitTask class.\n\n    Instance of this class is awaitable.\n    '

    def __init__(self, frame: Frame, predicateBody: str, title: str, polling: Union[(str, int)], timeout: float, loop: asyncio.AbstractEventLoop, *args: Any) -> None:
        if isinstance(polling, str):
            if (polling not in ['raf', 'mutation']):
                raise ValueError(
                    ''.join(['Unknown polling: ', '{}'.format(polling)]))
        elif isinstance(polling, (int, float)):
            if (polling <= 0):
                raise ValueError(
                    ''.join(['Cannot poll with non-positive interval: ', '{}'.format(polling)]))
        else:
            raise ValueError(
                ''.join(['Unknown polling option: ', '{}'.format(polling)]))
        self._frame = frame
        self._polling = polling
        self._timeout = timeout
        self._loop = loop
        if (args or helper.is_jsfunc(predicateBody)):
            self._predicateBody = ''.join(
                ['return (', '{}'.format(predicateBody), ')(...args)'])
        else:
            self._predicateBody = ''.join(
                ['return ', '{}'.format(predicateBody)])
        self._args = args
        self._runCount = 0
        self._terminated = False
        self._timeoutError = False
        frame._waitTasks.add(self)
        self.promise = self._loop.create_future()

        async def timer(timeout: Union[(int, float)]) -> None:
            (await asyncio.sleep((timeout / 1000)))
            self._timeoutError = True
            self.terminate(TimeoutError(''.join(['Waiting for ', '{}'.format(
                title), ' failed: timeout ', '{}'.format(timeout), 'ms exceeds.'])))
        if timeout:
            self._timeoutTimer = self._loop.create_task(timer(self._timeout))
        self._runningTask = self._loop.create_task(self.rerun())

    def __await__(self) -> Generator:
        'Make this class **awaitable**.'
        result = (yield from self.promise)
        if isinstance(result, Exception):
            raise result
        return result

    def terminate(self, error: Exception) -> None:
        'Terminate this task.'
        self._terminated = True
        if (not self.promise.done()):
            self.promise.set_result(error)
        self._cleanup()

    async def rerun(self) -> None:
        'Start polling.'
        runCount = self._runCount = (self._runCount + 1)
        success = None
        error = None
        try:
            context = (await self._frame.executionContext())
            if (context is None):
                raise PageError('No execution context.')
            success = (await context.evaluateHandle(waitForPredicatePageFunction, self._predicateBody, self._polling, self._timeout, *self._args))
        except Exception as e:
            error = e
        if self.promise.done():
            return
        if (self._terminated or (runCount != self._runCount)):
            if success:
                (await success.dispose())
            return
        try:
            if ((not error) and success and (await self._frame.evaluate('s => !s', success))):
                (await success.dispose())
                return
        except NetworkError:
            if (success is not None):
                (await success.dispose())
            return
        if (isinstance(error, NetworkError) and ('Execution context was destroyed' in error.args[0])):
            return
        if (isinstance(error, NetworkError) and ('Cannot find context with specified id' in error.args[0])):
            return
        if error:
            self.promise.set_exception(error)
        else:
            self.promise.set_result(success)
        self._cleanup()

    def _cleanup(self) -> None:
        if (self._timeout and (not self._timeoutError)):
            self._timeoutTimer.cancel()
        self._frame._waitTasks.remove(self)


waitForPredicatePageFunction = "\nasync function waitForPredicatePageFunction(predicateBody, polling, timeout, ...args) {\n  const predicate = new Function('...args', predicateBody);\n  let timedOut = false;\n  if (timeout)\n    setTimeout(() => timedOut = true, timeout);\n  if (polling === 'raf')\n    return await pollRaf();\n  if (polling === 'mutation')\n    return await pollMutation();\n  if (typeof polling === 'number')\n    return await pollInterval(polling);\n\n  /**\n   * @return {!Promise<*>}\n   */\n  function pollMutation() {\n    const success = predicate.apply(null, args);\n    if (success)\n      return Promise.resolve(success);\n\n    let fulfill;\n    const result = new Promise(x => fulfill = x);\n    const observer = new MutationObserver(mutations => {\n      if (timedOut) {\n        observer.disconnect();\n        fulfill();\n      }\n      const success = predicate.apply(null, args);\n      if (success) {\n        observer.disconnect();\n        fulfill(success);\n      }\n    });\n    observer.observe(document, {\n      childList: true,\n      subtree: true,\n      attributes: true\n    });\n    return result;\n  }\n\n  /**\n   * @return {!Promise<*>}\n   */\n  function pollRaf() {\n    let fulfill;\n    const result = new Promise(x => fulfill = x);\n    onRaf();\n    return result;\n\n    function onRaf() {\n      if (timedOut) {\n        fulfill();\n        return;\n      }\n      const success = predicate.apply(null, args);\n      if (success)\n        fulfill(success);\n      else\n        requestAnimationFrame(onRaf);\n    }\n  }\n\n  /**\n   * @param {number} pollInterval\n   * @return {!Promise<*>}\n   */\n  function pollInterval(pollInterval) {\n    let fulfill;\n    const result = new Promise(x => fulfill = x);\n    onTimeout();\n    return result;\n\n    function onTimeout() {\n      if (timedOut) {\n        fulfill();\n        return;\n      }\n      const success = predicate.apply(null, args);\n      if (success)\n        fulfill(success);\n      else\n        setTimeout(onTimeout, pollInterval);\n    }\n  }\n}\n"
