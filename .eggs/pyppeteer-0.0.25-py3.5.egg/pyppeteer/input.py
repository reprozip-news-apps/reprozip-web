
'Keyboard and Mouse module.'
import asyncio
from typing import Any, Dict, TYPE_CHECKING
from pyppeteer.connection import CDPSession
from pyppeteer.errors import PyppeteerError
from pyppeteer.us_keyboard_layout import keyDefinitions
from pyppeteer.util import merge_dict
if TYPE_CHECKING:
    from typing import Set


class Keyboard(object):
    "Keyboard class provides as api for managing a virtual keyboard.\n\n    The high level api is :meth:`type`, which takes raw characters and\n    generate proper keydown, keypress/input, and keyup events on your page.\n\n    For finer control, you can use :meth:`down`, :meth:`up`, and\n    :meth:`sendCharacter` to manually fire events as if they were generated\n    from a real keyboard.\n\n    An example of holding down ``Shift`` in order to select and delete some\n    text:\n\n    .. code::\n\n        await page.keyboard.type('Hello, World!')\n        await page.keyboard.press('ArrowLeft')\n\n        await page.keyboard.down('Shift')\n        for i in ' World':\n            await page.keyboard.press('ArrowLeft')\n        await page.keyboard.up('Shift')\n\n        await page.keyboard.press('Backspace')\n        # Result text will end up saying 'Hello!'.\n\n    An example of pressing ``A``:\n\n    .. code::\n\n        await page.keyboard.down('Shift')\n        await page.keyboard.press('KeyA')\n        await page.keyboard.up('Shift')\n    "

    def __init__(self, client: CDPSession) -> None:
        self._client = client
        self._modifiers = 0
        self._pressedKeys = set()

    async def down(self, key: str, options: dict = None, **kwargs: Any) -> None:
        'Dispatch a ``keydown`` event with ``key``.\n\n        If ``key`` is a single character and no modifier keys besides ``Shift``\n        are being held down, and a ``keypress``/``input`` event will also\n        generated. The ``text`` option can be specified to force an ``input``\n        event to be generated.\n\n        If ``key`` is a modifier key, like ``Shift``, ``Meta``, or ``Alt``,\n        subsequent key presses will be sent with that modifier active. To\n        release the modifier key, use :meth:`up` method.\n\n        :arg str key: Name of key to press, such as ``ArrowLeft``.\n        :arg dict options: Option can have ``text`` field, and if this option\n            specified, generate an input event with this text.\n\n        .. note::\n            Modifier keys DO influence :meth:`down`. Holding down ``shift``\n            will type the text in upper case.\n        '
        options = merge_dict(options, kwargs)
        description = self._keyDescriptionForString(key)
        autoRepeat = (description['code'] in self._pressedKeys)
        self._pressedKeys.add(description['code'])
        self._modifiers |= self._modifierBit(description['key'])
        text = options.get('text')
        if (text is None):
            text = description['text']
        (await self._client.send('Input.dispatchKeyEvent', {
            'type': ('keyDown' if text else 'rawKeyDown'),
            'modifiers': self._modifiers,
            'windowsVirtualKeyCode': description['keyCode'],
            'code': description['code'],
            'key': description['key'],
            'text': text,
            'unmodifiedText': text,
            'autoRepeat': autoRepeat,
            'location': description['location'],
            'isKeypad': (description['location'] == 3),
        }))

    def _modifierBit(self, key: str) -> int:
        if (key == 'Alt'):
            return 1
        if (key == 'Control'):
            return 2
        if (key == 'Meta'):
            return 4
        if (key == 'Shift'):
            return 8
        return 0

    def _keyDescriptionForString(self, keyString: str) -> Dict:
        shift = (self._modifiers & 8)
        description = {
            'key': '',
            'keyCode': 0,
            'code': '',
            'text': '',
            'location': 0,
        }
        definition = keyDefinitions.get(keyString)
        if (not definition):
            raise PyppeteerError(
                ''.join(['Unknown key: ', '{}'.format(keyString)]))
        if ('key' in definition):
            description['key'] = definition['key']
        if (shift and definition.get('shiftKey')):
            description['key'] = definition['shiftKey']
        if ('keyCode' in definition):
            description['keyCode'] = definition['keyCode']
        if (shift and definition.get('shiftKeyCode')):
            description['keyCode'] = definition['shiftKeyCode']
        if ('code' in definition):
            description['code'] = definition['code']
        if ('location' in definition):
            description['location'] = definition['location']
        if (len(description['key']) == 1):
            description['text'] = description['key']
        if ('text' in definition):
            description['text'] = definition['text']
        if (shift and definition.get('shiftText')):
            description['text'] = definition['shiftText']
        if (self._modifiers & (~ 8)):
            description['text'] = ''
        return description

    async def up(self, key: str) -> None:
        'Dispatch a ``keyup`` event of the ``key``.\n\n        :arg str key: Name of key to release, such as ``ArrowLeft``.\n        '
        description = self._keyDescriptionForString(key)
        self._modifiers &= (~ self._modifierBit(description['key']))
        if (description['code'] in self._pressedKeys):
            self._pressedKeys.remove(description['code'])
        (await self._client.send('Input.dispatchKeyEvent', {
            'type': 'keyUp',
            'modifiers': self._modifiers,
            'key': description['key'],
            'windowsVirtualKeyCode': description['keyCode'],
            'code': description['code'],
            'location': description['location'],
        }))

    async def sendCharacter(self, char: str) -> None:
        'Send character into the page.\n\n        This method dispatches a ``keypress`` and ``input`` event. This does\n        not send a ``keydown`` or ``keyup`` event.\n\n        .. note::\n            Modifier keys DO NOT effect :meth:`sendCharacter`. Holding down\n            ``shift`` will not type the text in upper case.\n        '
        (await self._client.send('Input.dispatchKeyEvent', {
            'type': 'char',
            'modifiers': self._modifiers,
            'text': char,
            'key': char,
            'unmodifiedText': char,
        }))

    async def type(self, text: str, options: Dict = None, **kwargs: Any) -> None:
        'Type characters into a focused element.\n\n        This method sends ``keydown``, ``keypress``/``input``, and ``keyup``\n        event for each character in the ``text``.\n\n        To press a special key, like ``Control`` or ``ArrowDown``, use\n        :meth:`press` method.\n\n        :arg str text: Text to type into a focused element.\n        :arg dict options: Options can have ``delay`` (int|float) field, which\n          specifies time to wait between key presses in milliseconds. Defaults\n          to 0.\n\n        .. note::\n            Modifier keys DO NOT effect :meth:`type`. Holding down ``shift``\n            will not type the text in upper case.\n        '
        options = merge_dict(options, kwargs)
        delay = options.get('delay', 0)
        for char in text:
            if (char in keyDefinitions):
                (await self.press(char, {
                    'delay': delay,
                }))
            else:
                (await self.sendCharacter(char))
            if delay:
                (await asyncio.sleep((delay / 1000)))

    async def press(self, key: str, options: Dict = None, **kwargs: Any) -> None:
        'Press ``key``.\n\n        If ``key`` is a single character and no modifier keys besides\n        ``Shift`` are being held down, a ``keypress``/``input`` event will also\n        generated. The ``text`` option can be specified to force an input event\n        to be generated.\n\n        :arg str key: Name of key to press, such as ``ArrowLeft``.\n\n        This method accepts the following options:\n\n        * ``text`` (str): If specified, generates an input event with this\n          text.\n        * ``delay`` (int|float): Time to wait between ``keydown`` and\n          ``keyup``. Defaults to 0.\n\n        .. note::\n            Modifier keys DO effect :meth:`press`. Holding down ``Shift`` will\n            type the text in upper case.\n        '
        options = merge_dict(options, kwargs)
        (await self.down(key, options))
        if ('delay' in options):
            (await asyncio.sleep((options['delay'] / 1000)))
        (await self.up(key))


class Mouse(object):
    'Mouse class.'

    def __init__(self, client: CDPSession, keyboard: Keyboard) -> None:
        self._client = client
        self._keyboard = keyboard
        self._x = 0.0
        self._y = 0.0
        self._button = 'none'

    async def move(self, x: float, y: float, options: dict = None, **kwargs: Any) -> None:
        'Move mouse cursor (dispatches a ``mousemove`` event).\n\n        Options can accepts ``steps`` (int) field. If this ``steps`` option\n        specified, Sends intermediate ``mousemove`` events. Defaults to 1.\n        '
        options = merge_dict(options, kwargs)
        fromX = self._x
        fromY = self._y
        self._x = x
        self._y = y
        steps = options.get('steps', 1)
        for i in range(1, (steps + 1)):
            x = round((fromX + ((self._x - fromX) * (i / steps))))
            y = round((fromY + ((self._y - fromY) * (i / steps))))
            (await self._client.send('Input.dispatchMouseEvent', {
                'type': 'mouseMoved',
                'button': self._button,
                'x': x,
                'y': y,
                'modifiers': self._keyboard._modifiers,
            }))

    async def click(self, x: float, y: float, options: dict = None, **kwargs: Any) -> None:
        'Click button at (``x``, ``y``).\n\n        Shortcut to :meth:`move`, :meth:`down`, and :meth:`up`.\n\n        This method accepts the following options:\n\n        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to\n          ``left``.\n        * ``clickCount`` (int): defaults to 1.\n        * ``delay`` (int|float): Time to wait between ``mousedown`` and\n          ``mouseup`` in milliseconds. Defaults to 0.\n        '
        options = merge_dict(options, kwargs)
        (await self.move(x, y))
        (await self.down(options))
        if (options and options.get('delay')):
            (await asyncio.sleep((options.get('delay', 0) / 1000)))
        (await self.up(options))

    async def down(self, options: dict = None, **kwargs: Any) -> None:
        'Press down button (dispatches ``mousedown`` event).\n\n        This method accepts the following options:\n\n        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to\n          ``left``.\n        * ``clickCount`` (int): defaults to 1.\n        '
        options = merge_dict(options, kwargs)
        self._button = options.get('button', 'left')
        (await self._client.send('Input.dispatchMouseEvent', {
            'type': 'mousePressed',
            'button': self._button,
            'x': self._x,
            'y': self._y,
            'modifiers': self._keyboard._modifiers,
            'clickCount': (options.get('clickCount') or 1),
        }))

    async def up(self, options: dict = None, **kwargs: Any) -> None:
        'Release pressed button (dispatches ``mouseup`` event).\n\n        This method accepts the following options:\n\n        * ``button`` (str): ``left``, ``right``, or ``middle``, defaults to\n          ``left``.\n        * ``clickCount`` (int): defaults to 1.\n        '
        options = merge_dict(options, kwargs)
        self._button = 'none'
        (await self._client.send('Input.dispatchMouseEvent', {
            'type': 'mouseReleased',
            'button': options.get('button', 'left'),
            'x': self._x,
            'y': self._y,
            'modifiers': self._keyboard._modifiers,
            'clickCount': (options.get('clickCount') or 1),
        }))


class Touchscreen(object):
    'Touchscreen class.'

    def __init__(self, client: CDPSession, keyboard: Keyboard) -> None:
        'Make new touchscreen object.'
        self._client = client
        self._keyboard = keyboard

    async def tap(self, x: float, y: float) -> None:
        'Tap (``x``, ``y``).\n\n        Dispatches a ``touchstart`` and ``touchend`` event.\n        '
        touchPoints = [{
            'x': round(x),
            'y': round(y),
        }]
        (await self._client.send('Input.dispatchTouchEvent', {
            'type': 'touchStart',
            'touchPoints': touchPoints,
            'modifiers': self._keyboard._modifiers,
        }))
        (await self._client.send('Input.dispatchTouchEvent', {
            'type': 'touchEnd',
            'touchPoints': [],
            'modifiers': self._keyboard._modifiers,
        }))
