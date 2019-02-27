
'Browser module.'
import logging
from subprocess import Popen
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Optional
from pyee import EventEmitter
from pyppeteer.connection import Connection
from pyppeteer.errors import BrowserError
from pyppeteer.page import Page
from pyppeteer.target import Target
logger = logging.getLogger(__name__)


class Browser(EventEmitter):
    'Browser class.\n\n    A Browser object is created when pyppeteer connects to chrome, either\n    through :func:`~pyppeteer.launcher.launch` or\n    :func:`~pyppeteer.launcher.connect`.\n    '
    Events = SimpleNamespace(TargetCreated='targetcreated', TargetDestroyed='targetdestroyed',
                             TargetChanged='targetchanged', Disconnected='disconnected')

    def __init__(self, connection: Connection, contextIds: List[str], ignoreHTTPSErrors: bool, setDefaultViewport: bool, process: Optional[Popen] = None, closeCallback: Callable[([], Awaitable[None])] = None, **kwargs: Any) -> None:
        super().__init__()
        self._ignoreHTTPSErrors = ignoreHTTPSErrors
        self._setDefaultViewport = setDefaultViewport
        self._process = process
        self._screenshotTaskQueue = []
        self._connection = connection

        def _dummy_callback() -> Awaitable[None]:
            fut = self._connection._loop.create_future()
            fut.set_result(None)
            return fut
        if closeCallback:
            self._closeCallback = closeCallback
        else:
            self._closeCallback = _dummy_callback
        self._defaultContext = BrowserContext(self, None)
        self._contexts = dict()
        for contextId in contextIds:
            self._contexts[contextId] = BrowserContext(self, contextId)
        self._targets = dict()
        self._connection.setClosedCallback(
            (lambda: self.emit(Browser.Events.Disconnected)))
        self._connection.on('Target.targetCreated', self._targetCreated)
        self._connection.on('Target.targetDestroyed', self._targetDestroyed)
        self._connection.on('Target.targetInfoChanged',
                            self._targetInfoChanged)

    @property
    def process(self) -> Optional[Popen]:
        'Return process of this browser.\n\n        If browser instance is created by :func:`pyppeteer.launcher.connect`,\n        return ``None``.\n        '
        return self._process

    async def createIncogniteBrowserContext(self) -> 'BrowserContext':
        '[Deprecated] Miss spelled method.\n\n        Use :meth:`createIncognitoBrowserContext` method instead.\n        '
        logger.warning(
            'createIncogniteBrowserContext is deprecated. Use createIncognitoBrowserContext instead.')
        return (await self.createIncognitoBrowserContext())

    async def createIncognitoBrowserContext(self) -> 'BrowserContext':
        "Create a new incognito browser context.\n\n        This won't share cookies/cache with other browser contexts.\n\n        .. code::\n\n            browser = await launch()\n            # Create a new incognito browser context.\n            context = await browser.createIncognitoBrowserContext()\n            # Create a new page in a pristine context.\n            page = await context.newPage()\n            # Do stuff\n            await page.goto('https://example.com')\n            ...\n        "
        obj = (await self._connection.send('Target.createBrowserContext'))
        browserContextId = obj['browserContextId']
        context = BrowserContext(self, browserContextId)
        self._contexts[browserContextId] = context
        return context

    @property
    def browserContexts(self) -> List['BrowserContext']:
        'Return a list of all open browser contexts.\n\n        In a newly created browser, this will return a single instance of\n        ``[BrowserContext]``\n        '
        return ([self._defaultContext] + [context for context in self._contexts.values()])

    async def _disposeContext(self, contextId: str) -> None:
        (await self._connection.send('Target.disposeBrowserContext', {
            'browserContextId': contextId,
        }))
        self._contexts.pop(contextId, None)

    @staticmethod
    async def create(connection: Connection, contextIds: List[str], ignoreHTTPSErrors: bool, appMode: bool, process: Optional[Popen] = None, closeCallback: Callable[([], Awaitable[None])] = None, **kwargs: Any) -> 'Browser':
        'Create browser object.'
        browser = Browser(connection, contextIds,
                          ignoreHTTPSErrors, appMode, process, closeCallback)
        (await connection.send('Target.setDiscoverTargets', {
            'discover': True,
        }))
        return browser

    async def _targetCreated(self, event: Dict) -> None:
        targetInfo = event['targetInfo']
        browserContextId = targetInfo.get('browserContextId')
        if (browserContextId and (browserContextId in self._contexts)):
            context = self._contexts[browserContextId]
        else:
            context = self._defaultContext
        target = Target(targetInfo, context, (lambda: self._connection.createSession(
            targetInfo)), self._ignoreHTTPSErrors, self._setDefaultViewport, self._screenshotTaskQueue, self._connection._loop)
        if (targetInfo['targetId'] in self._targets):
            raise BrowserError('target should not exist before create.')
        self._targets[targetInfo['targetId']] = target
        if (await target._initializedPromise):
            self.emit(Browser.Events.TargetCreated, target)
            context.emit(BrowserContext.Events.TargetCreated, target)

    async def _targetDestroyed(self, event: Dict) -> None:
        target = self._targets[event['targetId']]
        del self._targets[event['targetId']]
        target._closedCallback()
        if (await target._initializedPromise):
            self.emit(Browser.Events.TargetDestroyed, target)
            target.browserContext.emit(
                BrowserContext.Events.TargetDestroyed, target)
        target._initializedCallback(False)

    async def _targetInfoChanged(self, event: Dict) -> None:
        target = self._targets.get(event['targetInfo']['targetId'])
        if (not target):
            raise BrowserError('target should exist before targetInfoChanged')
        previousURL = target.url
        wasInitialized = target._isInitialized
        target._targetInfoChanged(event['targetInfo'])
        if (wasInitialized and (previousURL != target.url)):
            self.emit(Browser.Events.TargetChanged, target)
            target.browserContext.emit(
                BrowserContext.Events.TargetChanged, target)

    @property
    def wsEndpoint(self) -> str:
        'Return websocket end point url.'
        return self._connection.url

    async def newPage(self) -> Page:
        'Make new page on this browser and return its object.'
        return (await self._defaultContext.newPage())

    async def _createPageInContext(self, contextId: Optional[str]) -> Page:
        options = {
            'url': 'about:blank',
        }
        if contextId:
            options['browserContextId'] = contextId
        targetId = (await self._connection.send('Target.createTarget', options)).get('targetId')
        target = self._targets.get(targetId)
        if (target is None):
            raise BrowserError('Failed to create target for page.')
        if (not (await target._initializedPromise)):
            raise BrowserError('Failed to create target for page.')
        page = (await target.page())
        if (page is None):
            raise BrowserError('Failed to create page.')
        return page

    def targets(self) -> List[Target]:
        'Get a list of all active targets inside the browser.\n\n        In case of multiple browser contexts, the method will return a list\n        with all the targets in all browser contexts.\n        '
        return [target for target in self._targets.values() if target._isInitialized]

    async def pages(self) -> List[Page]:
        'Get all pages of this browser.\n\n        Non visible pages, such as ``"background_page"``, will not be listed\n        here. You can find then using :meth:`pyppeteer.target.Target.page`.\n        '
        pages = []
        for target in self.targets():
            if (target.type == 'page'):
                page = (await target.page())
                if page:
                    pages.append(page)
        return pages

    async def version(self) -> str:
        'Get version of the browser.'
        version = (await self._getVersion())
        return version['product']

    async def userAgent(self) -> str:
        "Return browser's original user agent.\n\n        .. note::\n            Pages can override browser user agent with\n            :meth:`pyppeteer.page.Page.setUserAgent`.\n        "
        version = (await self._getVersion())
        return version.get('userAgent', '')

    async def close(self) -> None:
        'Close connections and terminate browser process.'
        (await self._closeCallback())

    async def disconnect(self) -> None:
        'Disconnect browser.'
        (await self._connection.dispose())

    def _getVersion(self) -> Awaitable:
        return self._connection.send('Browser.getVersion')


class BrowserContext(EventEmitter):
    'BrowserContext provides multiple independent browser sessions.\n\n    When a browser is launched, it has a single BrowserContext used by default.\n    The method `browser.newPage()` creates a page in the default browser\n    context.\n\n    If a page opens another page, e.g. with a ``window.open`` call, the popup\n    will belong to the parent page\'s browser context.\n\n    Pyppeteer allows creation of "incognito" browser context with\n    ``browser.createIncognitoBrowserContext()`` method.\n    "incognito" browser contexts don\'t write any browser data to disk.\n\n    .. code::\n\n        # Create new incognito browser context\n        context = await browser.createIncognitoBrowserContext()\n        # Create a new page inside context\n        page = await context.newPage()\n        # ... do stuff with page ...\n        await page.goto(\'https://example.com\')\n        # Dispose context once it\'s no longer needed\n        await context.close()\n    '
    Events = SimpleNamespace(TargetCreated='targetcreated',
                             TargetDestroyed='targetdestroyed', TargetChanged='targetchanged')

    def __init__(self, browser: Browser, contextId: Optional[str]) -> None:
        super().__init__()
        self._browser = browser
        self._id = contextId

    def targets(self) -> List[Target]:
        'Return a list of all active targets inside the browser context.'
        targets = []
        for target in self._browser.targets():
            if (target.browserContext == self):
                targets.append(target)
        return targets

    def isIncognite(self) -> bool:
        '[Deprecated] Miss spelled method.\n\n        Use :meth:`isIncognito` method instead.\n        '
        logger.warning('isIncognite is deprecated. Use isIncognito instead.')
        return self.isIncognito()

    def isIncognito(self) -> bool:
        'Return whether BrowserContext is incognito.\n\n        The default browser context is the only non-incognito browser context.\n\n        .. note::\n            The default browser context cannot be closed.\n        '
        return bool(self._id)

    async def newPage(self) -> Page:
        'Create a new page in the browser context.'
        return (await self._browser._createPageInContext(self._id))

    @property
    def browser(self) -> Browser:
        'Return the browser this browser context belongs to.'
        return self._browser

    async def close(self) -> None:
        'Close the browser context.\n\n        All the targets that belongs to the browser context will be closed.\n\n        .. note::\n            Only incognito browser context can be closed.\n        '
        if (self._id is None):
            raise BrowserError('Non-incognito profile cannot be closed')
        (await self._browser._disposeContext(self._id))
