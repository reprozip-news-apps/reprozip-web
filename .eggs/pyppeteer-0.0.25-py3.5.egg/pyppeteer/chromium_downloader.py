
'Chromium download module.'
from io import BytesIO
import logging
import os
from pathlib import Path
import stat
import sys
from zipfile import ZipFile
import urllib3
from tqdm import tqdm
from pyppeteer import __chromium_revision__, __pyppeteer_home__
logger = logging.getLogger(__name__)
DOWNLOADS_FOLDER = (Path(__pyppeteer_home__) / 'local-chromium')
DEFAULT_DOWNLOAD_HOST = 'https://storage.googleapis.com'
DOWNLOAD_HOST = os.environ.get(
    'PYPPETEER_DOWNLOAD_HOST', DEFAULT_DOWNLOAD_HOST)
BASE_URL = ''.join(['{}'.format(DOWNLOAD_HOST), '/chromium-browser-snapshots'])
REVISION = os.environ.get('PYPPETEER_CHROMIUM_REVISION', __chromium_revision__)
downloadURLs = {
    'linux': ''.join(['{}'.format(BASE_URL), '/Linux_x64/', '{}'.format(REVISION), '/chrome-linux.zip']),
    'mac': ''.join(['{}'.format(BASE_URL), '/Mac/', '{}'.format(REVISION), '/chrome-mac.zip']),
    'win32': ''.join(['{}'.format(BASE_URL), '/Win/', '{}'.format(REVISION), '/chrome-win32.zip']),
    'win64': ''.join(['{}'.format(BASE_URL), '/Win_x64/', '{}'.format(REVISION), '/chrome-win32.zip']),
}
chromiumExecutable = {
    'linux': (((DOWNLOADS_FOLDER / REVISION) / 'chrome-linux') / 'chrome'),
    'mac': ((((((DOWNLOADS_FOLDER / REVISION) / 'chrome-mac') / 'Chromium.app') / 'Contents') / 'MacOS') / 'Chromium'),
    'win32': (((DOWNLOADS_FOLDER / REVISION) / 'chrome-win32') / 'chrome.exe'),
    'win64': (((DOWNLOADS_FOLDER / REVISION) / 'chrome-win32') / 'chrome.exe'),
}


def current_platform() -> str:
    'Get current platform name by short string.'
    if sys.platform.startswith('linux'):
        return 'linux'
    elif sys.platform.startswith('darwin'):
        return 'mac'
    elif (sys.platform.startswith('win') or sys.platform.startswith('msys') or sys.platform.startswith('cyg')):
        if (sys.maxsize > ((2 ** 31) - 1)):
            return 'win64'
        return 'win32'
    raise OSError(('Unsupported platform: ' + sys.platform))


def get_url() -> str:
    'Get chromium download url.'
    return downloadURLs[current_platform()]


def download_zip(url: str) -> BytesIO:
    'Download data from url.'
    logger.warning(
        'start chromium download.\nDownload may take a few minutes.')
    urllib3.disable_warnings()
    with urllib3.PoolManager() as http:
        data = http.request('GET', url, preload_content=False)
        try:
            total_length = int(data.headers['content-length'])
        except (KeyError, ValueError, AttributeError):
            total_length = 0
        process_bar = tqdm(total=total_length)
        _data = BytesIO()
        for chunk in data.stream(10240):
            _data.write(chunk)
            process_bar.update(len(chunk))
        process_bar.close()
    logger.warning('\nchromium download done.')
    return _data


def extract_zip(data: BytesIO, path: Path) -> None:
    'Extract zipped data to path.'
    if (current_platform() == 'mac'):
        import subprocess
        import shutil
        zip_path = (path / 'chrome.zip')
        if (not path.exists()):
            path.mkdir(parents=True)
        with zip_path.open('wb') as f:
            f.write(data.getvalue())
        if (not shutil.which('unzip')):
            raise OSError(''.join(
                ['Failed to automatically extract chromium.Please unzip ', '{}'.format(zip_path), ' manually.']))
        proc = subprocess.run(['unzip', str(zip_path)], cwd=str(
            path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if (proc.returncode != 0):
            logger.error(proc.stdout.decode())
            raise OSError(
                ''.join(['Failed to unzip ', '{}'.format(zip_path), '.']))
        if (chromium_executable().exists() and zip_path.exists()):
            zip_path.unlink()
    else:
        with ZipFile(data) as zf:
            zf.extractall(str(path))
    exec_path = chromium_executable()
    if (not exec_path.exists()):
        raise IOError('Failed to extract chromium.')
    exec_path.chmod(
        (((exec_path.stat().st_mode | stat.S_IXOTH) | stat.S_IXGRP) | stat.S_IXUSR))
    logger.warning(''.join(['chromium extracted to: ', '{}'.format(path)]))


def download_chromium() -> None:
    'Download and extract chromium.'
    extract_zip(download_zip(get_url()), (DOWNLOADS_FOLDER / REVISION))


def chromium_excutable() -> Path:
    '[Deprecated] miss-spelled function.\n\n    Use `chromium_executable` instead.\n    '
    logger.warning(
        '`chromium_excutable` function is deprecated. Use `chromium_executable instead.')
    return chromium_executable()


def chromium_executable() -> Path:
    'Get path of the chromium executable.'
    return chromiumExecutable[current_platform()]


def check_chromium() -> bool:
    'Check if chromium is placed at correct path.'
    return chromium_executable().exists()
