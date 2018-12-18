import argparse
from pathlib import Path
import logging
import sys
import json
import subprocess
import signal
import time
import requests
import docker
import pychrome
from collections import deque
import os
import tarfile
from reprounzip import signals
from reprounzip.unpackers.docker import docker_setup, docker_run

logger = logging.getLogger('reprounzip.dj')
logger.setLevel(10)
if len(logger.handlers) < 1:
    console_handler = logging.StreamHandler()
    logger.addHandler(console_handler)

class SubprocessManager(object):

    def __init__(self):
        self.procs = []

    def register(self, proc):
        self.procs.append(proc)

    def shutdown(self):
        for p in self.procs:
            p.kill()
        logger.debug("all procs shut down")

subprocess_manager = SubprocessManager()

def shutdown(sig, frame):
    subprocess_manager.shutdown()
    sys.exit(0)

signal.signal(signal.SIGINT, shutdown)


# Wraps the wayback record service
class Recorder(object):

    def __init__(self, root_dir, quiet=False):
        self.root_dir = root_dir
        self.port = 8080
        self.quiet = quiet

    def start(self):
        args = {}
        if self.quiet:
            args['stdout'] = subprocess.DEVNULL
            args['stderr'] = subprocess.DEVNULL

        try:
            print(self.root_dir)
            self.proc = subprocess.Popen(['wayback', '--record', '--live', '-a', '--auto-interval', '5', '-d', self.root_dir], **args)

        except Exception as e:
            logger.debug(e)
            logger.warn("Wayback service failed to start")
            sys.exit(1)

        tries = 10
        success = False
        while (tries > 0):
            try:
                r = requests.get("http://localhost:{}".format(self.port))
                if r.status_code == 200:
                    success = True
                    break
                else:
                    raise Exception
            except Exception:
                tries -= 1
                logger.info("Waiting for Wayback to start, {} tries left".format(tries))
                time.sleep(5)

        if success:
            logger.info("Recorder successfully started")
        else:
            raise Exception("Recorder failed to start")

        return self

    def kill(self):
        res = self.proc.kill()
        return res


# Runs Chromium and drives it via CDP
class Driver(object):

    CHROMIUM_REVISION = 610995

    def __init__(self, cdp_port=9222, pywb_port=8080):
        self.cdp_port = cdp_port
        self.pywb_port = pywb_port
        self.chromium_executable = None
        os.environ['PYPPETEER_CHROMIUM_REVISION'] = str(self.CHROMIUM_REVISION)
        from pyppeteer import chromium_downloader
        self.chromium_downloader = chromium_downloader
        self.proc = None

    def start(self):
        self.chromium_executable = self.chromium_downloader.chromium_executable()
        logger.info(self.chromium_executable)

        if not self.chromium_executable.exists():
            logger.info("Downloading Chromium browser")
            self.chromium_downloader.download_chromium()

        logger.info("Chrome Executable: {}".format(self.chromium_executable))
        self.proc = subprocess.Popen([
            self.chromium_executable,
            '--remote-debugging-port={}'.format(self.cdp_port)],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)

        tries = 5; res = None
        while tries > 0:
            try:
                res = requests.get(cdp_url())
                break
            except Exception as e:
                time.sleep(5)
                tries -= 1
                logger.info("Waiting for browser to respond on port 9222")

        if res and res.status_code != 200:
            raise Exception("Bad status code from Chrome: {}".format(res.status_code))

        logger.info("Chromium is fired up and ready to go!")
        return self

    def cdp_url(self):
        return "http://localhost:{}".format(self.cdp_port)

    def kill(self):
        self.proc.kill()

    def record(self, entry_url, coll_name="warc-data"):
        url_queue = deque([entry_url])
        browser = pychrome.Browser(url=self.cdp_url())

        while len(url_queue):
            url_to_visit = url_queue[0]
            logger.info("Recording {}".format(url_to_visit))
            record_url = "http://localhost:{}/{}/record/{}".format(self.pywb_port, coll_name, url_to_visit)
            tab = browser.new_tab()
            tab.start()
            tab.call_method("Network.enable")

            seconds_since_something_happened = 0
            def reset_secs(**args):
                seconds_since_something_happened = 0
            tab.set_listener("Network.loadingFinished", reset_secs)
            tab.call_method("Page.navigate", url=record_url)
            while seconds_since_something_happened < 10:
                logger.info("Waiting for resources to load in browser")
                tab.wait(1)
                seconds_since_something_happened += 1

            # TODO: Depending on CLI flags, pause and let
            # the user do some manual recordriving
            tab.stop()
            browser.close_tab(tab)
            url_queue.popleft()
            return 0

def pack_warc(rpz_file, pywb_root, coll='warc-data'):
    logger.debug("pack warc")
    rpz = tarfile.open(Path(rpz_file), 'a')
    warc_path = '{}/collections/{}/archive'.format(pywb_root, coll)
    warc = sorted(os.listdir(warc_path))[-1]
    rpz.add('{}/{}'.format(warc_path, warc), arcname=warc, recursive=False)
    logger.debug(rpz.getmembers())
    rpz.close()
    # Todo: add indexes or make sure playback includes indexing

def record(args):
    rpz_file = args.pack[0]
    rpz_path = Path(rpz_file)
    if not rpz_path.exists():
        logger.critical("Can't Find RPZ file")
        sys.exit(1)

    target = Path(args.target[0])
    if target.exists() and not args.skip_setup:
        logger.critical("Target directory exists")
        sys.exit(1)

    if not target.exists() and args.skip_setup:
        logger.critical("Target directory does not exist")
        sys.exit(1)

    port = 80
    if args.port:
        port = args.port

    # TODO: make sure port is clear

    args.__setattr__('base_image', None)
    args.__setattr__('install_pkgs', None)
    args.__setattr__('image_name', None)
    args.__setattr__('docker_cmd', "docker")
    args.__setattr__('docker_option', [])

    if not args.skip_setup:
        docker_setup(args)
        subprocess.Popen(['wb-manager', 'init', 'warc-data'], cwd=args.target[0])

    args.__setattr__('detach', True)
    args.__setattr__('expose_port', ['{}:{}'.format(args.port, args.port)])
    args.__setattr__('x11', None)
    args.__setattr__('cmdline', None)
    args.__setattr__('run', None)
    args.__setattr__('x11_display', None)
    args.__setattr__('pass_env', None)
    args.__setattr__('set_env', None)

    if not args.skip_run:
        docker_run(args)

    container_id = subprocess.check_output(args.docker_cmd.split() + ['ps', '-l', '-q']).decode('ascii')[:-1]

    container_name = json.loads(subprocess.check_output(args.docker_cmd.split() + ['container', 'inspect', container_id]).decode('ascii'))[0]['Name'][1:]

    tries = 20
    success = False
    while (tries > 0):
        try:
            r = requests.get("http://localhost:{}".format(args.port))
            if r.status_code == 200:
                success = True
                break
            else:
                raise Exception
        except Exception:
            tries -= 1
            print("Waiting for site to start, {} tries left".format(tries))
            time.sleep(5)

    if success:
        print("Site successfully started")
    else:
        raise Exception("Failed to start site")

    # above can setup replay too

    recorder = Recorder(args.target[0], args.quiet).start()
    subprocess_manager.register(recorder)

    driver = Driver().start()
    subprocess_manager.register(driver)

    logger.info("Start recording")
    driver.record("http://localhost:{}".format(port))
    logger.info("Done recording: shutting down...")
    subprocess_manager.shutdown()

    sys.exit(0)

    # TODO
    # check the warc
    # ask user if they need to do manual browse
    # clenup and exit


def replay(args):
    print("Not implemented")


def setup(parser, **kwargs):
    """Records site assets to a warc file and replays the site

    You will need Docker to be installed on your machine.

    record                  Generate the warc and add it to the .rpz

    replay                  Replay the site using the warc.
                            (includes reprounzip docker run)

    For example:

        $ reprounzip dj record my_data_journalism_site.rpz target [--port]
        $ reprounzip dj replay my_data_journalism_site.rpz target [--port]

    """
    subparsers = parser.add_subparsers(title="actions",
                                       metavar='', help=argparse.SUPPRESS)

    def add_opt_rpz_file(parser):
        parser.add_argument('pack', nargs=1, help="RPZ file")


    parser_record = subparsers.add_parser('record')
    add_opt_rpz_file(parser_record)
    parser_record.add_argument('target', nargs=1, help="target directory")
    parser_record.add_argument('--port', dest='port', help="webserver port")
    parser_record.add_argument('--skip-setup', action='store_true', help="skip reprounzip setup")
    parser_record.add_argument('--skip-run', action='store_true', help="skip reprounzip run")
    parser_record.add_argument('--quiet', action='store_true', help="shhhhhhh")


    parser_record.set_defaults(func=record)

    parser_replay = subparsers.add_parser('replay')
    add_opt_rpz_file(parser_replay)
