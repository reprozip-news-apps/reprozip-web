
'Element handle module.'
import copy
import logging
import math
import os.path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from pyppeteer.connection import CDPSession
from pyppeteer.execution_context import ExecutionContext, JSHandle
from pyppeteer.errors import ElementHandleError, NetworkError
from pyppeteer.helper import debugError
from pyppeteer.util import merge_dict
if TYPE_CHECKING:
    from pyppeteer.frame_manager import Frame, FrameManager
logger = logging.getLogger(__name__)


class ElementHandle(JSHandle):
    'ElementHandle class.\n\n    This class represents an in-page DOM element. ElementHandle can be created\n    by the :meth:`pyppeteer.page.Page.querySelector` method.\n\n    ElementHandle prevents DOM element from garbage collection unless the\n    handle is disposed. ElementHandles are automatically disposed when their\n    origin frame gets navigated.\n\n    ElementHandle isinstance can be used as arguments in\n    :meth:`pyppeteer.page.Page.querySelectorEval` and\n    :meth:`pyppeteer.page.Page.evaluate` methods.\n    '

    def __init__(self, context: ExecutionContext, client: CDPSession, remoteObject: dict, page: Any, frameManager: 'FrameManager') -> None:
        super().__init__(context, client, remoteObject)
        self._client = client
        self._remoteObject = remoteObject
        self._page = page
        self._frameManager = frameManager
        self._disposed = False

    def asElement(self) -> 'ElementHandle':
        'Return this ElementHandle.'
        return self

    async def contentFrame(self) -> Optional['Frame']:
        'Return the content frame for the element handle.\n\n        Return ``None`` if this handle is not referencing iframe.\n        '
        nodeInfo = (await self._client.send('DOM.describeNode', {
            'objectId': self._remoteObject.get('objectId'),
        }))
        node_obj = nodeInfo.get('node', {

        })
        if (not isinstance(node_obj.get('frameId'), str)):
            return None
        return self._frameManager.frame(node_obj['frameId'])

    async def _scrollIntoViewIfNeeded(self) -> None:
        error = (await self.executionContext.evaluate("\n            async element => {\n                if (!element.isConnected)\n                    return 'Node is detached from document';\n                if (element.nodeType !== Node.ELEMENT_NODE)\n                    return 'Node is not of type HTMLElement';\n                const visibleRatio = await new Promise(resolve => {\n                    const observer = new IntersectionObserver(entries => {\n                        resolve(entries[0].intersectionRatio);\n                        observer.disconnect();\n                    });\n                    observer.observe(element);\n                });\n                if (visibleRatio !== 1.0)\n                    element.scrollIntoView({\n                        block: 'center',\n                        inline: 'center',\n                        behavior: 'instant',\n                    });\n                return false;\n            }", self))
        if error:
            raise ElementHandleError(error)

    async def _clickablePoint(self) -> Dict[(str, float)]:
        result = None
        try:
            result = (await self._client.send('DOM.getContentQuads', {
                'objectId': self._remoteObject.get('objectId'),
            }))
        except Exception as e:
            debugError(logger, e)
        if ((not result) or (not result.get('quads'))):
            raise ElementHandleError(
                'Node is either not visible or not an HTMLElement')
        quads = []
        for _quad in result.get('quads'):
            _q = self._fromProtocolQuad(_quad)
            if (_computeQuadArea(_q) > 1):
                quads.append(_q)
        if (not quads):
            raise ElementHandleError(
                'Node is either not visible or not an HTMLElement')
        quad = quads[0]
        x = 0
        y = 0
        for point in quad:
            x += point['x']
            y += point['y']
        return {
            'x': (x / 4),
            'y': (y / 4),
        }

    async def _getBoxModel(self) -> Optional[Dict]:
        try:
            result = (await self._client.send('DOM.getBoxModel', {
                'objectId': self._remoteObject.get('objectId'),
            }))
        except NetworkError as e:
            debugError(logger, e)
            result = None
        return result

    def _fromProtocolQuad(self, quad: List[int]) -> List[Dict[(str, int)]]:
        return [{
            'x': quad[0],
            'y': quad[1],
        }, {
            'x': quad[2],
            'y': quad[3],
        }, {
            'x': quad[4],
            'y': quad[5],
        }, {
            'x': quad[6],
            'y': quad[7],
        }]

    async def hover(self) -> None:
        'Move mouse over to center of this element.\n\n        If needed, this method scrolls element into view. If this element is\n        detached from DOM tree, the method raises an ``ElementHandleError``.\n        '
        (await self._scrollIntoViewIfNeeded())
        obj = (await self._clickablePoint())
        x = obj.get('x', 0)
        y = obj.get('y', 0)
        (await self._page.mouse.move(x, y))

    async def click(self, options: dict = None, **kwargs: Any) -> None:
        'Click the center of this element.\n\n        If needed, this method scrolls element into view. If the element is\n        detached from DOM, the method raises ``ElementHandleError``.\n\n        ``options`` can contain the following fields:\n\n        * ``button`` (str): ``left``, ``right``, of ``middle``, defaults to\n          ``left``.\n        * ``clickCount`` (int): Defaults to 1.\n        * ``delay`` (int|float): Time to wait between ``mousedown`` and\n          ``mouseup`` in milliseconds. Defaults to 0.\n        '
        options = merge_dict(options, kwargs)
        (await self._scrollIntoViewIfNeeded())
        obj = (await self._clickablePoint())
        x = obj.get('x', 0)
        y = obj.get('y', 0)
        (await self._page.mouse.click(x, y, options))

    async def uploadFile(self, *filePaths: str) -> dict:
        'Upload files.'
        files = [os.path.abspath(p) for p in filePaths]
        objectId = self._remoteObject.get('objectId')
        return (await self._client.send('DOM.setFileInputFiles', {
            'objectId': objectId,
            'files': files,
        }))

    async def tap(self) -> None:
        'Tap the center of this element.\n\n        If needed, this method scrolls element into view. If the element is\n        detached from DOM, the method raises ``ElementHandleError``.\n        '
        (await self._scrollIntoViewIfNeeded())
        center = (await self._clickablePoint())
        x = center.get('x', 0)
        y = center.get('y', 0)
        (await self._page.touchscreen.tap(x, y))

    async def focus(self) -> None:
        'Focus on this element.'
        (await self.executionContext.evaluate('element => element.focus()', self))

    async def type(self, text: str, options: Dict = None, **kwargs: Any) -> None:
        'Focus the element and then type text.\n\n        Details see :meth:`pyppeteer.input.Keyboard.type` method.\n        '
        options = merge_dict(options, kwargs)
        (await self.focus())
        (await self._page.keyboard.type(text, options))

    async def press(self, key: str, options: Dict = None, **kwargs: Any) -> None:
        'Press ``key`` onto the element.\n\n        This method focuses the element, and then uses\n        :meth:`pyppeteer.input.keyboard.down` and\n        :meth:`pyppeteer.input.keyboard.up`.\n\n        :arg str key: Name of key to press, such as ``ArrowLeft``.\n\n        This method accepts the following options:\n\n        * ``text`` (str): If specified, generates an input event with this\n          text.\n        * ``delay`` (int|float): Time to wait between ``keydown`` and\n          ``keyup``. Defaults to 0.\n        '
        options = merge_dict(options, kwargs)
        (await self.focus())
        (await self._page.keyboard.press(key, options))

    async def boundingBox(self) -> Optional[Dict[(str, float)]]:
        'Return bounding box of this element.\n\n        If the element is not visible, return ``None``.\n\n        This method returns dictionary of bounding box, which contains:\n\n        * ``x`` (int): The X coordinate of the element in pixels.\n        * ``y`` (int): The Y coordinate of the element in pixels.\n        * ``width`` (int): The width of the element in pixels.\n        * ``height`` (int): The height of the element in pixels.\n        '
        result = (await self._getBoxModel())
        if (not result):
            return None
        quad = result['model']['border']
        x = min(quad[0], quad[2], quad[4], quad[6])
        y = min(quad[1], quad[3], quad[5], quad[7])
        width = (max(quad[0], quad[2], quad[4], quad[6]) - x)
        height = (max(quad[1], quad[3], quad[5], quad[7]) - y)
        return {
            'x': x,
            'y': y,
            'width': width,
            'height': height,
        }

    async def boxModel(self) -> Optional[Dict]:
        "Return boxes of element.\n\n        Return ``None`` if element is not visible. Boxes are represented as an\n        list of points; each Point is a dictionary ``{x, y}``. Box points are\n        sorted clock-wise.\n\n        Returned value is a dictionary with the following fields:\n\n        * ``content`` (List[Dict]): Content box.\n        * ``padding`` (List[Dict]): Padding box.\n        * ``border`` (List[Dict]): Border box.\n        * ``margin`` (List[Dict]): Margin box.\n        * ``width`` (int): Element's width.\n        * ``height`` (int): Element's height.\n        "
        result = (await self._getBoxModel())
        if (not result):
            return None
        model = result.get('model', {

        })
        return {
            'content': self._fromProtocolQuad(model.get('content')),
            'padding': self._fromProtocolQuad(model.get('padding')),
            'border': self._fromProtocolQuad(model.get('border')),
            'margin': self._fromProtocolQuad(model.get('margin')),
            'width': model.get('width'),
            'height': model.get('height'),
        }

    async def screenshot(self, options: Dict = None, **kwargs: Any) -> bytes:
        'Take a screenshot of this element.\n\n        If the element is detached from DOM, this method raises an\n        ``ElementHandleError``.\n\n        Available options are same as :meth:`pyppeteer.page.Page.screenshot`.\n        '
        options = merge_dict(options, kwargs)
        needsViewportReset = False
        boundingBox = (await self.boundingBox())
        if (not boundingBox):
            raise ElementHandleError(
                'Node is either not visible or not an HTMLElement')
        original_viewport = copy.deepcopy(self._page.viewport)
        if ((boundingBox['width'] > original_viewport['width']) or (boundingBox['height'] > original_viewport['height'])):
            newViewport = {
                'width': max(original_viewport['width'], math.ceil(boundingBox['width'])),
                'height': max(original_viewport['height'], math.ceil(boundingBox['height'])),
            }
            new_viewport = copy.deepcopy(original_viewport)
            new_viewport.update(newViewport)
            (await self._page.setViewport(new_viewport))
            needsViewportReset = True
        (await self._scrollIntoViewIfNeeded())
        boundingBox = (await self.boundingBox())
        if (not boundingBox):
            raise ElementHandleError(
                'Node is either not visible or not an HTMLElement')
        _obj = (await self._client.send('Page.getLayoutMetrics'))
        pageX = _obj['layoutViewport']['pageX']
        pageY = _obj['layoutViewport']['pageY']
        clip = {

        }
        clip.update(boundingBox)
        clip['x'] = (clip['x'] + pageX)
        clip['y'] = (clip['y'] + pageY)
        opt = {
            'clip': clip,
        }
        opt.update(options)
        imageData = (await self._page.screenshot(opt))
        if needsViewportReset:
            (await self._page.setViewport(original_viewport))
        return imageData

    async def querySelector(self, selector: str) -> Optional['ElementHandle']:
        'Return first element which matches ``selector`` under this element.\n\n        If no element matches the ``selector``, returns ``None``.\n        '
        handle = (await self.executionContext.evaluateHandle('(element, selector) => element.querySelector(selector)', self, selector))
        element = handle.asElement()
        if element:
            return element
        (await handle.dispose())
        return None

    async def querySelectorAll(self, selector: str) -> List['ElementHandle']:
        'Return all elements which match ``selector`` under this element.\n\n        If no element matches the ``selector``, returns empty list (``[]``).\n        '
        arrayHandle = (await self.executionContext.evaluateHandle('(element, selector) => element.querySelectorAll(selector)', self, selector))
        properties = (await arrayHandle.getProperties())
        (await arrayHandle.dispose())
        result = []
        for prop in properties.values():
            elementHandle = prop.asElement()
            if elementHandle:
                result.append(elementHandle)
        return result

    async def querySelectorEval(self, selector: str, pageFunction: str, *args: Any) -> Any:
        "Run ``Page.querySelectorEval`` within the element.\n\n        This method runs ``document.querySelector`` within the element and\n        passes it as the first argument to ``pageFunction``. If there is no\n        element matching ``selector``, the method raises\n        ``ElementHandleError``.\n\n        If ``pageFunction`` returns a promise, then wait for the promise to\n        resolve and return its value.\n\n        ``ElementHandle.Jeval`` is a shortcut of this method.\n\n        Example:\n\n        .. code:: python\n\n            tweetHandle = await page.querySelector('.tweet')\n            assert (await tweetHandle.querySelectorEval('.like', 'node => node.innerText')) == 100\n            assert (await tweetHandle.Jeval('.retweets', 'node => node.innerText')) == 10\n        "
        elementHandle = (await self.querySelector(selector))
        if (not elementHandle):
            raise ElementHandleError(''.join(
                ['Error: failed to find element matching selector "', '{}'.format(selector), '"']))
        result = (await self.executionContext.evaluate(pageFunction, elementHandle, *args))
        (await elementHandle.dispose())
        return result

    async def querySelectorAllEval(self, selector: str, pageFunction: str, *args: Any) -> Any:
        'Run ``Page.querySelectorAllEval`` within the element.\n\n        This method runs ``Array.from(document.querySelectorAll)`` within the\n        element and passes it as the first argument to ``pageFunction``. If\n        there is no element matching ``selector``, the method raises\n        ``ElementHandleError``.\n\n        If ``pageFunction`` returns a promise, then wait for the promise to\n        resolve and return its value.\n\n        Example:\n\n        .. code:: html\n\n            <div class="feed">\n                <div class="tweet">Hello!</div>\n                <div class="tweet">Hi!</div>\n            </div>\n\n        .. code:: python\n\n            feedHandle = await page.J(\'.feed\')\n            assert (await feedHandle.JJeval(\'.tweet\', \'(nodes => nodes.map(n => n.innerText))\')) == [\'Hello!\', \'Hi!\']\n        '
        arrayHandle = (await self.executionContext.evaluateHandle('(element, selector) => Array.from(element.querySelectorAll(selector))', self, selector))
        result = (await self.executionContext.evaluate(pageFunction, arrayHandle, *args))
        (await arrayHandle.dispose())
        return result
    J = querySelector
    JJ = querySelectorAll
    Jeval = querySelectorEval
    JJeval = querySelectorAllEval

    async def xpath(self, expression: str) -> List['ElementHandle']:
        'Evaluate the XPath expression relative to this elementHandle.\n\n        If there are no such elements, return an empty list.\n\n        :arg str expression: XPath string to be evaluated.\n        '
        arrayHandle = (await self.executionContext.evaluateHandle('(element, expression) => {\n                const document = element.ownerDocument || element;\n                const iterator = document.evaluate(expression, element, null,\n                    XPathResult.ORDERED_NODE_ITERATOR_TYPE);\n                const array = [];\n                let item;\n                while ((item = iterator.iterateNext()))\n                    array.push(item);\n                return array;\n\n            }', self, expression))
        properties = (await arrayHandle.getProperties())
        (await arrayHandle.dispose())
        result = []
        for property in properties.values():
            elementHandle = property.asElement()
            if elementHandle:
                result.append(elementHandle)
        return result
    Jx = xpath

    async def isIntersectingViewport(self) -> bool:
        'Return ``True`` if the element is visible in the viewport.'
        return (await self.executionContext.evaluate('async element => {\n            const visibleRatio = await new Promise(resolve => {\n                const observer = new IntersectionObserver(entries => {\n                    resolve(entries[0].intersectionRatio);\n                    observer.disconnect();\n                });\n                observer.observe(element);\n            });\n            return visibleRatio > 0;\n        }', self))


def _computeQuadArea(quad: List[Dict]) -> float:
    area = 0
    for (i, _) in enumerate(quad):
        p1 = quad[i]
        p2 = quad[((i + 1) % len(quad))]
        area += (((p1['x'] * p2['y']) - (p2['x'] * p1['y'])) / 2)
    return area
