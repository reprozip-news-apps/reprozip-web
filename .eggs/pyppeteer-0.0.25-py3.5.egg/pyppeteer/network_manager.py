
'Network Manager module.'
import asyncio
import base64
from collections import OrderedDict
import copy
import json
import logging
from types import SimpleNamespace
from typing import Awaitable, Dict, List, Optional, Union, TYPE_CHECKING
from urllib.parse import unquote
from pyee import EventEmitter
from pyppeteer.connection import CDPSession
from pyppeteer.errors import NetworkError
from pyppeteer.frame_manager import FrameManager, Frame
from pyppeteer.helper import debugError
from pyppeteer.multimap import Multimap
if TYPE_CHECKING:
    from typing import Set
logger = logging.getLogger(__name__)


class NetworkManager(EventEmitter):
    'NetworkManager class.'
    Events = SimpleNamespace(Request='request', Response='response',
                             RequestFailed='requestfailed', RequestFinished='requestfinished')

    def __init__(self, client: CDPSession, frameManager: FrameManager) -> None:
        'Make new NetworkManager.'
        super().__init__()
        self._client = client
        self._frameManager = frameManager
        self._requestIdToRequest = dict()
        self._interceptionIdToRequest = dict()
        self._extraHTTPHeaders = OrderedDict()
        self._offline = False
        self._credentials = None
        self._attemptedAuthentications = set()
        self._userRequestInterceptionEnabled = False
        self._protocolRequestInterceptionEnabled = False
        self._requestHashToRequestIds = Multimap()
        self._requestHashToInterceptionIds = Multimap()
        self._client.on('Network.requestWillBeSent', self._onRequestWillBeSent)
        self._client.on('Network.requestIntercepted',
                        self._onRequestIntercepted)
        self._client.on('Network.requestServedFromCache',
                        self._onRequestServedFromCache)
        self._client.on('Network.responseReceived', self._onResponseReceived)
        self._client.on('Network.loadingFinished', self._onLoadingFinished)
        self._client.on('Network.loadingFailed', self._onLoadingFailed)

    async def authenticate(self, credentials: Dict[(str, str)]) -> None:
        'Provide credentials for http auth.'
        self._credentials = credentials
        (await self._updateProtocolRequestInterception())

    async def setExtraHTTPHeaders(self, extraHTTPHeaders: Dict[(str, str)]) -> None:
        'Set extra http headers.'
        self._extraHTTPHeaders = OrderedDict()
        for (k, v) in extraHTTPHeaders.items():
            if (not isinstance(v, str)):
                raise TypeError(''.join(['Expected value of header "', '{}'.format(
                    k), '" to be string, but ', '{}'.format(type(v)), ' is found.']))
            self._extraHTTPHeaders[k.lower()] = v
        (await self._client.send('Network.setExtraHTTPHeaders', {
            'headers': self._extraHTTPHeaders,
        }))

    def extraHTTPHeaders(self) -> Dict[(str, str)]:
        'Get extra http headers.'
        return dict(**self._extraHTTPHeaders)

    async def setOfflineMode(self, value: bool) -> None:
        'Change offline mode enable/disable.'
        if (self._offline == value):
            return
        self._offline = value
        (await self._client.send('Network.emulateNetworkConditions', {
            'offline': self._offline,
            'latency': 0,
            'downloadThroughput': (- 1),
            'uploadThroughput': (- 1),
        }))

    async def setUserAgent(self, userAgent: str) -> None:
        'Set user agent.'
        (await self._client.send('Network.setUserAgentOverride', {
            'userAgent': userAgent,
        }))

    async def setRequestInterception(self, value: bool) -> None:
        'Enable request interception.'
        self._userRequestInterceptionEnabled = value
        (await self._updateProtocolRequestInterception())

    async def _updateProtocolRequestInterception(self) -> None:
        enabled = (self._userRequestInterceptionEnabled or bool(
            self._credentials))
        if (enabled == self._protocolRequestInterceptionEnabled):
            return
        self._protocolRequestInterceptionEnabled = enabled
        patterns = ([{
            'urlPattern': '*',
        }] if enabled else [])
        (await asyncio.gather(self._client.send('Network.setCacheDisabled', {
            'cacheDisabled': enabled,
        }), self._client.send('Network.setRequestInterception', {
            'patterns': patterns,
        })))

    async def _send(self, method: str, msg: dict) -> None:
        try:
            (await self._client.send(method, msg))
        except Exception as e:
            debugError(logger, e)

    def _onRequestIntercepted(self, event: dict) -> None:
        if event.get('authChallenge'):
            response = 'Default'
            if (event['interceptionId'] in self._attemptedAuthentications):
                response = 'CancelAuth'
            elif self._credentials:
                response = 'ProvideCredentials'
                self._attemptedAuthentications.add(event['interceptionId'])
            username = getattr(self, '_credentials', {

            }).get('username')
            password = getattr(self, '_credentials', {

            }).get('password')
            self._client._loop.create_task(self._send('Network.continueInterceptedRequest', {
                'interceptionId': event['interceptionId'],
                'authChallengeResponse': {
                    'response': response,
                    'username': username,
                    'password': password,
                },
            }))
            return
        if ((not self._userRequestInterceptionEnabled) and self._protocolRequestInterceptionEnabled):
            self._client._loop.create_task(self._send('Network.continueInterceptedRequest', {
                'interceptionId': event['interceptionId'],
            }))
        if ('redirectUrl' in event):
            request = self._interceptionIdToRequest.get(
                event.get('interceptionId', ''))
            if request:
                self._handleRequestRedirect(request, event.get('responseStatusCode', 0), event.get('responseHeaders', {

                }), False, False, None)
                self._handleRequestStart(request._requestId, event.get('interceptionId', ''), event.get('redirectUrl', ''), event.get('isNavigationRequest', False), event.get('resourceType', ''), event.get('request', {

                }), event.get('frameId'), request._redirectChain)
            return
        requestHash = generateRequestHash(event['request'])
        requestId = self._requestHashToRequestIds.firstValue(requestHash)
        if requestId:
            self._requestHashToRequestIds.delete(requestHash, requestId)
            self._handleRequestStart(requestId, event['interceptionId'], event['request']['url'],
                                     event['isNavigationRequest'], event['resourceType'], event['request'], event['frameId'], [])
        else:
            self._requestHashToInterceptionIds.set(
                requestHash, event['interceptionId'])
            self._handleRequestStart(None, event['interceptionId'], event['request']['url'],
                                     event['isNavigationRequest'], event['resourceType'], event['request'], event['frameId'], [])

    def _onRequestServedFromCache(self, event: Dict) -> None:
        request = self._requestIdToRequest.get(event.get('requestId'))
        if request:
            request._fromMemoryCache = True

    def _handleRequestRedirect(self, request: 'Request', redirectStatus: int, redirectHeaders: Dict, fromDiskCache: bool, fromServiceWorker: bool, securityDetails: Dict = None) -> None:
        response = Response(self._client, request, redirectStatus,
                            redirectHeaders, fromDiskCache, fromServiceWorker, securityDetails)
        request._response = response
        request._redirectChain.append(request)
        response._bodyLoadedPromiseFulfill(NetworkError(
            'Response body is unavailable for redirect response'))
        self._requestIdToRequest.pop(request._requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.Response, response)
        self.emit(NetworkManager.Events.RequestFinished, request)

    def _handleRequestStart(self, requestId: Optional[str], interceptionId: str, url: str, isNavigationRequest: bool, resourceType: str, requestPayload: Dict, frameId: Optional[str], redirectChain: List['Request']) -> None:
        frame = None
        if (frameId and (self._frameManager is not None)):
            frame = self._frameManager.frame(frameId)
        request = Request(self._client, requestId, interceptionId, isNavigationRequest,
                          self._userRequestInterceptionEnabled, url, resourceType, requestPayload, frame, redirectChain)
        if requestId:
            self._requestIdToRequest[requestId] = request
        if interceptionId:
            self._interceptionIdToRequest[interceptionId] = request
        self.emit(NetworkManager.Events.Request, request)

    def _onRequestWillBeSent(self, event: dict) -> None:
        if self._protocolRequestInterceptionEnabled:
            if event.get('redirectResponse'):
                return
            requestHash = generateRequestHash(event['request'])
            interceptionId = self._requestHashToInterceptionIds.firstValue(
                requestHash)
            request = self._interceptionIdToRequest.get(interceptionId)
            if request:
                request._requestId = event['requestId']
                self._requestIdToRequest[event['requestId']] = request
                self._requestHashToInterceptionIds.delete(
                    requestHash, interceptionId)
            else:
                self._requestHashToRequestIds.set(
                    requestHash, event['requestId'])
            return
        redirectChain = []
        if event.get('redirectResponse'):
            request = self._requestIdToRequest[event['requestId']]
            if request:
                redirectResponse = event.get('redirectResponse', {

                })
                self._handleRequestRedirect(request, redirectResponse.get('status'), redirectResponse.get('headers'), redirectResponse.get(
                    'fromDiskCache'), redirectResponse.get('fromServiceWorker'), redirectResponse.get('securityDetails'))
                redirectChain = request._redirectChain
        isNavigationRequest = (
            (event['requestId'] == event['loaderId']) and (event['type'] == 'Document'))
        self._handleRequestStart(event.get('requestId', ''), '', event.get('request', {

        }).get('url', ''), isNavigationRequest, event.get('type', ''), event.get('request', {

        }), event.get('frameId'), redirectChain)

    def _onResponseReceived(self, event: dict) -> None:
        request = self._requestIdToRequest.get(event['requestId'])
        if (not request):
            return
        _resp = event.get('response', {

        })
        response = Response(self._client, request, _resp.get('status', 0), _resp.get('headers', {

        }), _resp.get('fromDiskCache'), _resp.get('fromServiceWorker'), _resp.get('securityDetails'))
        request._response = response
        self.emit(NetworkManager.Events.Response, response)

    def _onLoadingFinished(self, event: dict) -> None:
        request = self._requestIdToRequest.get(event.get('requestId', ''))
        if (not request):
            return
        response = request.response
        if response:
            response._bodyLoadedPromiseFulfill(None)
        self._requestIdToRequest.pop(request._requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.RequestFinished, request)

    def _onLoadingFailed(self, event: dict) -> None:
        request = self._requestIdToRequest.get(event['requestId'])
        if (not request):
            return
        request._failureText = event.get('errorText')
        response = request.response
        if response:
            response._bodyLoadedPromiseFulfill(None)
        self._requestIdToRequest.pop(request._requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.RequestFailed, request)


class Request(object):
    "Request class.\n\n    Whenever the page sends a request, such as for a network resource, the\n    following events are emitted by pyppeteer's page:\n\n    - ``'request'``: emitted when the request is issued by the page.\n    - ``'response'``: emitted when/if the response is received for the request.\n    - ``'requestfinished'``: emitted when the response body is downloaded and\n      the request is complete.\n\n    If request fails at some point, then instead of ``'requestfinished'`` event\n    (and possibly instead of ``'response'`` event), the ``'requestfailed'``\n    event is emitted.\n\n    If request gets a ``'redirect'`` response, the request is successfully\n    finished with the ``'requestfinished'`` event, and a new request is issued\n    to a redirect url.\n    "

    def __init__(self, client: CDPSession, requestId: Optional[str], interceptionId: str, isNavigationRequest: bool, allowInterception: bool, url: str, resourceType: str, payload: dict, frame: Optional[Frame], redirectChain: List['Request']) -> None:
        self._client = client
        self._requestId = requestId
        self._isNavigationRequest = isNavigationRequest
        self._interceptionId = interceptionId
        self._allowInterception = allowInterception
        self._interceptionHandled = False
        self._response = None
        self._failureText = None
        self._url = url
        self._resourceType = resourceType.lower()
        self._method = payload.get('method')
        self._postData = payload.get('postData')
        headers = payload.get('headers', {

        })
        self._headers = {k.lower(): v for (k, v) in headers.items()}
        self._frame = frame
        self._redirectChain = redirectChain
        self._fromMemoryCache = False

    @property
    def url(self) -> str:
        'URL of this request.'
        return self._url

    @property
    def resourceType(self) -> str:
        'Resource type of this request perceived by the rendering engine.\n\n        ResourceType will be one of the following: ``document``,\n        ``stylesheet``, ``image``, ``media``, ``font``, ``script``,\n        ``texttrack``, ``xhr``, ``fetch``, ``eventsource``, ``websocket``,\n        ``manifest``, ``other``.\n        '
        return self._resourceType

    @property
    def method(self) -> Optional[str]:
        "Return this request's method (GET, POST, etc.)."
        return self._method

    @property
    def postData(self) -> Optional[str]:
        'Return post body of this request.'
        return self._postData

    @property
    def headers(self) -> Dict:
        'Return a dictionary of HTTP headers of this request.\n\n        All header names are lower-case.\n        '
        return self._headers

    @property
    def response(self) -> Optional['Response']:
        'Return matching :class:`Response` object, or ``None``.\n\n        If the response has not been received, return ``None``.\n        '
        return self._response

    @property
    def frame(self) -> Optional[Frame]:
        'Return a matching :class:`~pyppeteer.frame_manager.frame` object.\n\n        Return ``None`` if navigating to error page.\n        '
        return self._frame

    def isNavigationRequest(self) -> bool:
        "Whether this request is driving frame's navigation."
        return self._isNavigationRequest

    @property
    def redirectChain(self) -> List['Request']:
        'Return chain of requests initiated to fetch a resource.\n\n        * If there are no redirects and request was successful, the chain will\n          be empty.\n        * If a server responds with at least a single redirect, then the chain\n          will contain all the requests that were redirected.\n\n        ``redirectChain`` is shared between all the requests of the same chain.\n        '
        return copy.copy(self._redirectChain)

    def failure(self) -> Optional[Dict]:
        "Return error text.\n\n        Return ``None`` unless this request was failed, as reported by\n        ``requestfailed`` event.\n\n        When request failed, this method return dictionary which has a\n        ``errorText`` field, which contains human-readable error message, e.g.\n        ``'net::ERR_RAILED'``.\n        "
        if (not self._failureText):
            return None
        return {
            'errorText': self._failureText,
        }

    async def continue_(self, overrides: Dict = None) -> None:
        'Continue request with optional request overrides.\n\n        To use this method, request interception should be enabled by\n        :meth:`pyppeteer.page.Page.setRequestInterception`. If request\n        interception is not enabled, raise ``NetworkError``.\n\n        ``overrides`` can have the following fields:\n\n        * ``url`` (str): If set, the request url will be changed.\n        * ``method`` (str): If set, change the request method (e.g. ``GET``).\n        * ``postData`` (str): If set, change the post data or request.\n        * ``headers`` (dict): If set, change the request HTTP header.\n        '
        if (overrides is None):
            overrides = {

            }
        if (not self._allowInterception):
            raise NetworkError('Request interception is not enabled.')
        if self._interceptionHandled:
            raise NetworkError('Request is already handled.')
        self._interceptionHandled = True
        opt = {
            'interceptionId': self._interceptionId,
        }
        opt.update(overrides)
        try:
            (await self._client.send('Network.continueInterceptedRequest', opt))
        except Exception as e:
            debugError(logger, e)

    async def respond(self, response: Dict) -> None:
        'Fulfills request with given response.\n\n        To use this, request interception should by enabled by\n        :meth:`pyppeteer.page.Page.setRequestInterception`. Request\n        interception is not enabled, raise ``NetworkError``.\n\n        ``response`` is a dictionary which can have the following fields:\n\n        * ``status`` (int): Response status code, defaults to 200.\n        * ``headers`` (dict): Optional response headers.\n        * ``contentType`` (str): If set, equals to setting ``Content-Type``\n          response header.\n        * ``body`` (str|bytes): Optional response body.\n        '
        if self._url.startswith('data:'):
            return
        if (not self._allowInterception):
            raise NetworkError('Request interception is not enabled.')
        if self._interceptionHandled:
            raise NetworkError('Request is already handled.')
        self._interceptionHandled = True
        if (response.get('body') and isinstance(response['body'], str)):
            responseBody = response['body'].encode('utf-8')
        else:
            responseBody = response.get('body')
        responseHeaders = {

        }
        if response.get('headers'):
            for header in response['headers']:
                responseHeaders[header.lower()] = response['headers'][header]
        if response.get('contentType'):
            responseHeaders['content-type'] = response['contentType']
        if (responseBody and ('content-length' not in responseHeaders)):
            responseHeaders['content-length'] = len(responseBody)
        statusCode = response.get('status', 200)
        statusText = statusTexts.get(statusCode, '')
        statusLine = ''.join(
            ['HTTP/1.1 ', '{}'.format(statusCode), ' ', '{}'.format(statusText)])
        CRLF = '\r\n'
        text = (statusLine + CRLF)
        for header in responseHeaders:
            text = ''.join(['{}'.format(text), '{}'.format(header), ': ', '{}'.format(
                responseHeaders[header]), '{}'.format(CRLF)])
        text = (text + CRLF)
        responseBuffer = text.encode('utf-8')
        if responseBody:
            responseBuffer = (responseBuffer + responseBody)
        rawResponse = base64.b64encode(responseBuffer).decode('ascii')
        try:
            (await self._client.send('Network.continueInterceptedRequest', {
                'interceptionId': self._interceptionId,
                'rawResponse': rawResponse,
            }))
        except Exception as e:
            debugError(logger, e)

    async def abort(self, errorCode: str = 'failed') -> None:
        "Abort request.\n\n        To use this, request interception should be enabled by\n        :meth:`pyppeteer.page.Page.setRequestInterception`.\n        If request interception is not enabled, raise ``NetworkError``.\n\n        ``errorCode`` is an optional error code string. Defaults to ``failed``,\n        could be one of the following:\n\n        - ``aborted``: An operation was aborted (due to user action).\n        - ``accessdenied``: Permission to access a resource, other than the\n          network, was denied.\n        - ``addressunreachable``: The IP address is unreachable. This usually\n          means that there is no route to the specified host or network.\n        - ``blockedbyclient``: The client chose to block the request.\n        - ``blockedbyresponse``: The request failed because the request was\n          delivered along with requirements which are not met\n          ('X-Frame-Options' and 'Content-Security-Policy' ancestor check,\n          for instance).\n        - ``connectionaborted``: A connection timeout as a result of not\n          receiving an ACK for data sent.\n        - ``connectionclosed``: A connection was closed (corresponding to a TCP\n          FIN).\n        - ``connectionfailed``: A connection attempt failed.\n        - ``connectionrefused``: A connection attempt was refused.\n        - ``connectionreset``: A connection was reset (corresponding to a TCP\n          RST).\n        - ``internetdisconnected``: The Internet connection has been lost.\n        - ``namenotresolved``: The host name could not be resolved.\n        - ``timedout``: An operation timed out.\n        - ``failed``: A generic failure occurred.\n        "
        errorReason = errorReasons[errorCode]
        if (not errorReason):
            raise NetworkError('Unknown error code: {}'.format(errorCode))
        if (not self._allowInterception):
            raise NetworkError('Request interception is not enabled.')
        if self._interceptionHandled:
            raise NetworkError('Request is already handled.')
        self._interceptionHandled = True
        try:
            (await self._client.send('Network.continueInterceptedRequest', dict(interceptionId=self._interceptionId, errorReason=errorReason)))
        except Exception as e:
            debugError(logger, e)


errorReasons = {
    'aborted': 'Aborted',
    'accessdenied': 'AccessDenied',
    'addressunreachable': 'AddressUnreachable',
    'blockedbyclient': 'BlockedByClient',
    'blockedbyresponse': 'BlockedByResponse',
    'connectionaborted': 'ConnectionAborted',
    'connectionclosed': 'ConnectionClosed',
    'connectionfailed': 'ConnectionFailed',
    'connectionrefused': 'ConnectionRefused',
    'connectionreset': 'ConnectionReset',
    'internetdisconnected': 'InternetDisconnected',
    'namenotresolved': 'NameNotResolved',
    'timedout': 'TimedOut',
    'failed': 'Failed',
}


class Response(object):
    'Response class represents responses which are received by ``Page``.'

    def __init__(self, client: CDPSession, request: Request, status: int, headers: Dict[(str, str)], fromDiskCache: bool, fromServiceWorker: bool, securityDetails: Dict = None) -> None:
        self._client = client
        self._request = request
        self._status = status
        self._contentPromise = self._client._loop.create_future()
        self._bodyLoadedPromise = self._client._loop.create_future()
        self._url = request.url
        self._fromDiskCache = fromDiskCache
        self._fromServiceWorker = fromServiceWorker
        self._headers = {k.lower(): v for (k, v) in headers.items()}
        self._securityDetails = {

        }
        if securityDetails:
            self._securityDetails = SecurityDetails(
                securityDetails['subjectName'], securityDetails['issuer'], securityDetails['validFrom'], securityDetails['validTo'], securityDetails['protocol'])

    def _bodyLoadedPromiseFulfill(self, value: Optional[Exception]) -> None:
        self._bodyLoadedPromise.set_result(value)

    @property
    def url(self) -> str:
        'URL of the response.'
        return self._url

    @property
    def ok(self) -> bool:
        'Return bool whether this request is successful (200-299) or not.'
        return ((self._status == 0) or (200 <= self._status <= 299))

    @property
    def status(self) -> int:
        'Status code of the response.'
        return self._status

    @property
    def headers(self) -> Dict:
        'Return dictionary of HTTP headers of this response.\n\n        All header names are lower-case.\n        '
        return self._headers

    @property
    def securityDetails(self) -> Union[(Dict, 'SecurityDetails')]:
        'Return security details associated with this response.\n\n        Security details if the response was received over the secure\n        connection, or `None` otherwise.\n        '
        return self._securityDetails

    async def _bufread(self) -> bytes:
        result = (await self._bodyLoadedPromise)
        if isinstance(result, Exception):
            raise result
        response = (await self._client.send('Network.getResponseBody', {
            'requestId': self._request._requestId,
        }))
        body = response.get('body', b'')
        if response.get('base64Encoded'):
            return base64.b64decode(body)
        return body

    def buffer(self) -> Awaitable[bytes]:
        'Return awaitable which resolves to bytes with response body.'
        if (not self._contentPromise.done()):
            return self._client._loop.create_task(self._bufread())
        return self._contentPromise

    async def text(self) -> str:
        'Get text representation of response body.'
        content = (await self.buffer())
        if isinstance(content, str):
            return content
        else:
            return content.decode('utf-8')

    async def json(self) -> dict:
        'Get JSON representation of response body.'
        content = (await self.text())
        return json.loads(content)

    @property
    def request(self) -> Request:
        'Get matching :class:`Request` object.'
        return self._request

    @property
    def fromCache(self) -> bool:
        "Return ``True`` if the response was served from cache.\n\n        Here `cache` is either the browser's disk cache or memory cache.\n        "
        return (self._fromDiskCache or self._request._fromMemoryCache)

    @property
    def fromServiceWorker(self) -> bool:
        'Return ``True`` if the response was served by a service worker.'
        return self._fromServiceWorker


def generateRequestHash(request: dict) -> str:
    'Generate request hash.'
    normalizedURL = request.get('url', '')
    try:
        normalizedURL = unquote(normalizedURL)
    except Exception:
        pass
    _hash = {
        'url': normalizedURL,
        'method': request.get('method'),
        'postData': request.get('postData'),
        'headers': {

        },
    }
    if (not normalizedURL.startswith('data:')):
        headers = list(request['headers'].keys())
        headers.sort()
        for header in headers:
            headerValue = request['headers'][header]
            header = header.lower()
            if (header in ['accept', 'referer', 'x-devtools-emulate-network-conditions-client-id', 'cookie']):
                continue
            _hash['headers'][header] = headerValue
    return json.dumps(_hash)


class SecurityDetails(object):
    'Class represents responses which are received by page.'

    def __init__(self, subjectName: str, issuer: str, validFrom: int, validTo: int, protocol: str) -> None:
        self._subjectName = subjectName
        self._issuer = issuer
        self._validFrom = validFrom
        self._validTo = validTo
        self._protocol = protocol

    @property
    def subjectName(self) -> str:
        'Return the subject to which the certificate was issued to.'
        return self._subjectName

    @property
    def issuer(self) -> str:
        'Return a string with the name of issuer of the certificate.'
        return self._issuer

    @property
    def validFrom(self) -> int:
        'Return UnixTime of the start of validity of the certificate.'
        return self._validFrom

    @property
    def validTo(self) -> int:
        'Return UnixTime of the end of validity of the certificate.'
        return self._validTo

    @property
    def protocol(self) -> str:
        'Return string of with the security protocol, e.g. "TLS1.2".'
        return self._protocol


statusTexts = {
    '100': 'Continue',
    '101': 'Switching Protocols',
    '102': 'Processing',
    '200': 'OK',
    '201': 'Created',
    '202': 'Accepted',
    '203': 'Non-Authoritative Information',
    '204': 'No Content',
    '206': 'Partial Content',
    '207': 'Multi-Status',
    '208': 'Already Reported',
    '209': 'IM Used',
    '300': 'Multiple Choices',
    '301': 'Moved Permanently',
    '302': 'Found',
    '303': 'See Other',
    '304': 'Not Modified',
    '305': 'Use Proxy',
    '306': 'Switch Proxy',
    '307': 'Temporary Redirect',
    '308': 'Permanent Redirect',
    '400': 'Bad Request',
    '401': 'Unauthorized',
    '402': 'Payment Required',
    '403': 'Forbidden',
    '404': 'Not Found',
    '405': 'Method Not Allowed',
    '406': 'Not Acceptable',
    '407': 'Proxy Authentication Required',
    '408': 'Request Timeout',
    '409': 'Conflict',
    '410': 'Gone',
    '411': 'Length Required',
    '412': 'Precondition Failed',
    '413': 'Payload Too Large',
    '414': 'URI Too Long',
    '415': 'Unsupported Media Type',
    '416': 'Range Not Satisfiable',
    '417': 'Expectation Failed',
    '418': "I'm a teapot",
    '421': 'Misdirected Request',
    '422': 'Unprocessable Entity',
    '423': 'Locked',
    '424': 'Failed Dependency',
    '426': 'Upgrade Required',
    '428': 'Precondition Required',
    '429': 'Too Many Requests',
    '431': 'Request Header Fields Too Large',
    '451': 'Unavailable For Legal Reasons',
    '500': 'Internal Server Error',
    '501': 'Not Implemented',
    '502': 'Bad Gateway',
    '503': 'Service Unavailable',
    '504': 'Gateway Timeout',
    '505': 'HTTP Version Not Supported',
    '506': 'Variant Also Negotiates',
    '507': 'Insufficient Storage',
    '508': 'Loop Detected',
    '510': 'Not Extended',
    '511': 'Network Authentication Required',
}
