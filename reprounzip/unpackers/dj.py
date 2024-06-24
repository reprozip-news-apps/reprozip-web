import argparse
from pathlib import Path
import logging
import sys
import subprocess
import signal
import time
import requests
import websocket
import json
import docker
import docker.errors
import pychrome
import os
import shutil
import tarfile
from reprounzip.common import RPZPack
from reprounzip.unpackers.docker import docker_setup, docker_run, read_dict


logger = logging.getLogger('reprounzip.dj')
logger.setLevel(10)
if len(logger.handlers) < 1:
    console_handler = logging.StreamHandler()
    logger.addHandler(console_handler)


class InvalidRPZ(Exception):
    pass


class BadArgument(Exception):
    pass


class MissingWARCData(Exception):
    pass


class WARCPacker(object):

    @staticmethod
    def no_second_pass(rpz_file):
        with tarfile.open(str(rpz_file)) as tar:
            for name in tar.getnames():
                if name[0:9] == 'WARC_DATA':
                    raise InvalidRPZ(
                        'This RPZ archive '
                        'already contains WARC data')

    @staticmethod
    def data_path(filename, prefix=Path('WARC_DATA')):
        return prefix / filename.parts[-1]

    def __init__(self, rpz_file):
        self.tar = tarfile.open(str(rpz_file), 'a:')

    def add_warc_data(self, target, coll='warc-data'):
        coll_path = Path(target) / 'collections' / coll
        warc_path = coll_path / 'archive'
        try:
            warc = sorted(os.listdir(warc_path))[-1]
        except IndexError:
            raise MissingWARCData(warc_path)
        warc_path = warc_path / warc
        index_path = coll_path / 'indexes/autoindex.cdxj'
        for path in [warc_path, index_path]:
            self.tar.add(str(path),
                         str(WARCPacker.data_path(path)),
                         recursive=False)

    def close(self):
        self.tar.close()
        self.seen = None


class RPZPackWithWARC(RPZPack):

    def unpack_warc(self, target, coll='warc-data'):
        target = Path(target)
        for name in self.tar.getnames():
            if name[0:9] == 'WARC_DATA':
                member = self.tar.getmember(name)
                dest_path = target / 'collections' / coll
                if name[10:] == 'autoindex.cdxj':
                    dest_path = dest_path / 'indexes'
                else:
                    dest_path = dest_path / 'archive'
                member.name = name[10:]
                self.tar.extract(member, dest_path)


class SubprocessManager(object):

    def __init__(self):
        self.running = []

    def register(self, stopable):
        self.running.append(stopable)

    def shutdown(self):
        for r in self.running:
            logger.debug(r)
            try:
                r.stop()
            except docker.errors.NotFound:
                pass
        logger.debug("all jobs stopped")


class Wayback(object):
    PORT = 8080

    @staticmethod
    def wait_for_service(port):
        tries = 10
        success = False
        while (tries > 0):
            try:
                r = requests.get("http://localhost:{}".format(Wayback.PORT))
                if r.status_code == 200:
                    success = True
                    break
                else:
                    raise Exception
            except requests.RequestException:
                tries -= 1
                logger.info('Waiting for Wayback to start'
                            ', {} tries left'.format(tries))
                time.sleep(5)

        if success:
            return
        raise Exception("Wayback failed to start correctly")

    @classmethod
    def new_recorder(cls, root_dir, args):
        popen_args = [
            '--record',
            '--live',
            '-a',
            '--auto-interval',
            '5',
            '-d',
            root_dir]
        return cls(popen_args, args)

    @classmethod
    def new_replayer(cls, root_dir, args=None):
        popen_args = [
            '--proxy', 'warc-data', '-d', root_dir]
        return cls(popen_args, args)

    def __init__(self, proc_args, args=None):
        self.proc = None
        self.proc_args = proc_args
        self.output_args = {}
        if args and args.quiet:
            self.output_args['stdout'] = subprocess.DEVNULL
            self.output_args['stderr'] = subprocess.DEVNULL

    def stop(self):
        try:
            stop = self.proc.kill
        except AttributeError:
            pass
        else:
            stop()

    def start(self):
        try:
            proc_args = ['wayback', '-p', str(Wayback.PORT)] + self.proc_args
            logger.debug(proc_args)
            self.proc = subprocess.Popen(proc_args, **self.output_args)

        except Exception:
            logger.exception("Wayback service failed to start")
            raise

        Wayback.wait_for_service(Wayback.PORT)


# Runs Chromium and drives it via CDP
class Driver(object):

    CHROMIUM_REVISION = 610995
    CDP_PORT = 9222
    PYWB_HOST = PROXY_HOST = 'localhost'
    PROXY_PORT = 8081

    @classmethod
    def new_recording_driver(cls, coll_name):
        return cls('record', coll_name)

    @classmethod
    def new_replay_driver(cls):
        return cls('replay')

    def __init__(self, mode, coll_name=None):
        self.mode = mode
        if coll_name:
            self.coll_name = coll_name
        self.chromium_executable = None
        os.environ['PYPPETEER_CHROMIUM_REVISION'] = str(self.CHROMIUM_REVISION)
        from pyppeteer import chromium_downloader
        self.chromium_downloader = chromium_downloader
        self.proc = None
        self.chromium_executable = \
            self.chromium_downloader.chromium_executable()
        logger.info(self.chromium_executable)
        self.flags = []
        if self.mode == 'replay':
            self.flags = [
                '--proxy-server=http={}:{};https={}:{}'.format(
                    self.PROXY_HOST,
                    self.PROXY_PORT,
                    self.PROXY_HOST,
                    Wayback.PORT),
                '--ignore-certificate-errors',
                '--disk-cache-dir=/dev/null',
                '--disk-cache-size=1'
            ]
        elif self.mode == 'record':
            self.flags = [
                '--disk-cache-dir=/dev/null',
                '--disk-cache-size=1'
            ]

    def start(self):
        if not self.chromium_executable.exists():
            logger.info("Downloading Chromium browser")
            self.chromium_downloader.download_chromium()

        logger.info("Chrome Executable: {}".format(self.chromium_executable))

        self.proc = subprocess.Popen([
            self.chromium_executable,
            '--remote-debugging-port={}'.format(self.CDP_PORT),
            '--disable-notifications',
            '--disable-infobars',
            '--disable-breakpad',
            *self.flags
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        tries = 5
        res = None
        while tries > 0:
            try:
                res = requests.get(self.cdp_url() + '/json/version')
                break
            except requests.RequestException:
                time.sleep(5)
                tries -= 1
                logger.info("Waiting for browser to respond on port 9222")

        if res and res.status_code != 200:
            raise Exception("Bad status code from Chrome: "
                            "{}".format(res.status_code))

        self.browser_ws_url = res.json()['webSocketDebuggerUrl']
        self.browser = pychrome.Browser(url=self.cdp_url())
        self.tab_zero = self.browser.list_tab()[0]
        logger.info("Chromium is fired up and ready to go!")

    def cdp_url(self):
        return "http://localhost:{}".format(self.CDP_PORT)

    def stop(self):
        for t in self.browser.list_tab():
            try:
                t.stop()
            except pychrome.exceptions.RuntimeException:
                pass
        message = {
            'id': 9999,
            'method': 'Browser.close'
        }
        json_message = json.dumps(message)
        ws = websocket.create_connection(self.browser_ws_url)
        ws.send(json_message)
        time.sleep(1)
        ws.close()
        if self.proc:
            self.proc.terminate()

    def replay(self, url_to_visit):
        tab = self.browser.new_tab()
        tab.start()
        tab.call_method("Network.enable")
        tab.call_method("Page.navigate", url=url_to_visit)

    def record(self, url_to_visit, keep_open=False):
        logger.info("Recording {}".format(url_to_visit))
        record_url = "http://{}:{}/{}/record/{}".format(
            self.PYWB_HOST,
            Wayback.PORT,
            self.coll_name,
            url_to_visit)
        tab = self.browser.new_tab()
        tab.start()
        seconds_since_something_happened = [0]

        def reset_secs(**args):
            seconds_since_something_happened[0] = 0
        tab.set_listener("Network.loadingFinished", reset_secs)
        tab.call_method("Page.navigate", url=record_url)
        while seconds_since_something_happened[0] < 20:
            logger.info("Waiting for resources to load in browser")
            tab.wait(1)
            seconds_since_something_happened[0] += 1
        if keep_open:
            return 0
        tab.stop()
        self.browser.close_tab(tab)
        return 0


subprocess_manager = SubprocessManager()


def shutdown(sig, frame):
    subprocess_manager.shutdown()
    sys.exit(0)


def register(stopable):
    subprocess_manager.register(stopable)


def find_container(target):
    unpacked_info = read_dict(target)
    image_name = unpacked_info['current_image'].decode()
    client = docker.from_env()
    return list(c for c in client.containers.list()
                if c.image.tags.count("{}:latest".format(image_name)))[0]


def resource_path(project_path):
    return os.path.abspath(Path(
        os.path.dirname(os.path.realpath(__file__)),
        '../', '../',
        project_path
    ))


def cleanup(args):
    if args.skip_destroy or args.skip_run:
        return
    target = Path(args.target[0])
    container = find_container(target)
    image = container.image
    container.stop()
    container.remove()
    if not args.skip_setup:
        client = docker.from_env()
        try:
            client.images.remove(image.id)
        except docker.errors.APIError as e:
            print(str(e))
            force = input("Force image removal? (Y/n)")
            if force.upper() == 'Y':
                client.images.remove(image.id, force=True)
        finally:
            shutil.rmtree(str(target))



def wait_for_site(url):
    logger.debug(url)
    tries = 20
    success = False
    while tries > 0:
        try:
            r = requests.get(url)
            if r.status_code != 200:
                logger.debug(r.status_code)
            r.raise_for_status()
            success = True
            break
        except requests.RequestException:
            tries -= 1
            logger.info("Waiting for site to start, {} tries "
                        "left".format(tries))
            time.sleep(5)

    if success:
        logger.info("Site successfully responded")
    else:
        raise TimeoutError("No response from target site")


def run_site(args):
    if hasattr(args, 'pack'):
        rpz_path = Path(args.pack[0])
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

    args.__setattr__('base_image', None)
    args.__setattr__('install_pkgs', None)
    args.__setattr__('image_name', None)
    args.__setattr__('docker_cmd', "docker")
    args.__setattr__('docker_option', [])

    if not args.skip_setup:
        docker_setup(args)
        rpz = RPZPackWithWARC(args.pack[0])
        rpz.unpack_warc(target)

    if not args.skip_run:
        args.__setattr__('detach', True)
        args.__setattr__('expose_port', ['{}:{}'.format(args.port, args.port)])
        args.__setattr__('x11', None)
        args.__setattr__('cmdline', None)
        args.__setattr__('run', None)
        args.__setattr__('x11_display', None)
        args.__setattr__('pass_env', None)
        args.__setattr__('set_env', None)
        docker_run(args)

    if not Path(target / 'collections').is_dir():
        subprocess.Popen(['wb-manager', 'init',
                          'warc-data'], cwd=args.target[0])

    if hasattr(args, 'url'):
        url = args.url[0]
    else:
        url = "http://localhost:{}".format(args.port)
    wait_for_site(url)
    return url


def pack_it(args):
    try:
        packer = WARCPacker(Path(args.pack[0]))
        packer.add_warc_data(args.target[0])
        packer.close()
    except AttributeError:
        pass


def record(args):
    try:
        WARCPacker.no_second_pass(args.pack[0])
    except AttributeError:
        pass

    if args.skip_record:
        pack_it(args)
        return
    if args.quiet:
        logger.setLevel(30)
    try:
        url = run_site(args)
        signal.signal(signal.SIGINT, shutdown)

        logger.info("Start recording")
        recorder = Wayback.new_recorder(args.target[0], args)
        recorder.start()
        register(recorder)

        logger.info("Start browser")
        driver = Driver.new_recording_driver('warc-data')
        driver.start()
        register(driver)

        driver.record(url, args.keep_browser)
        time.sleep(5)  # ensure wayback finishes writing warc

        if args.keep_browser:
            input("Press Enter to stop recording and quit")
    except Exception:
        logger.critical("Failure to record")
        raise
    finally:
        subprocess_manager.shutdown()

    pack_it(args)
    cleanup(args)


def live_record(args):
    if args.url[0].find("http") != 0:
        message = "Expected a URL but got '{}'".format(args.url[0])
        raise BadArgument(message)
    args.skip_setup = True
    args.skip_run = True
    args.skip_record = False
    record(args)


def docker_pull_if_not_exists(client, image):
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        logger.info("Pulling Docker image %s... this may take a while",
                    image.split(':', 1)[0])
        client.images.pull(image)


def pywb_vols(target_dir, standalone=False):
    if standalone:
        vols = {
            'pywb/uwsgi.ini': '/uwsgi/uwsgi.ini',
            'pywb/standalone.py': '/app/app.py',
            'pywb/standalone-config.yaml': '/webarchive/config.yaml'
        }
    else:
        vols = {
            'pywb/proxy-config.yaml': '/webarchive/config.yaml'
        }

    vols['pywb/templates'] = '/webarchive/templates'
    vols[target_dir + '/collections'] = '/webarchive/collections'

    return dict((resource_path(k), {'bind': v}) for k, v in vols.items())


def set_hostname(args):
    if not args.hostname:
        return 'rpzdj-repl.ay'
    if args.hostname[0][0:7] == 'http://':
        return args.hostname[0][7:]
    if args.hostname[0][0:8] == 'https://':
        return args.hostname[0][8:]
    return args.hostname[0]


def playback(args):
    if args.quiet:
        logger.setLevel(30)
    rpz_name = Path(args.pack[0]).name
    replay_server_name = set_hostname(args)
    network = site_container = pywb_container = proxy_container = None
    proxy_port = 8081
    target_dir = os.path.abspath(args.target[0])
    try:
        run_site(args)
        site_container = find_container(Path(target_dir))

        signal.signal(signal.SIGINT, shutdown)

        logger.debug("Container {}".format(site_container.name))

        client = docker.from_env()
        docker_pull_if_not_exists(client, 'nginx:latest')
        docker_pull_if_not_exists(client, 'webrecorder/pywb:latest')

        network = client.networks.create(
            "rpzdj_{}".format(time.time_ns()),
            driver="bridge",
            attachable=True
        )
        logger.info("PROXY NETWORK {}".format(network.name))
        network.connect(site_container)

        vols = pywb_vols(target_dir, args.standalone)
        logger.info("PYWB Container with volumes: {}".format(str(vols)))
        pywb_container = client.containers.run(
            'webrecorder/pywb', detach=True, remove=True,
            name='pywb-playback', network=network.name,
            volumes=vols, user='root',
            ports={'8080/tcp': Wayback.PORT},
            environment=['RPZ_HOST=' + site_container.name +
                         ':' + args.port,
                         'RPZ_FAKE_URL=http://' + rpz_name])

        register(pywb_container)
        Wayback.wait_for_service(Wayback.PORT)

        if args.standalone:
            print("Point your browser to http://localhost:{}"
                  "/http://{}".format(Wayback.PORT, rpz_name))
        else:
            conf_string = subprocess.check_output(
                ['sed', '-e', 's/PROXIED_SERVER/{}:{}/'.format(
                    site_container.name, args.port),
                 '-e', 's/SERVER_NAME/{}/'.format(replay_server_name),
                 '-e', 's/PYWB_PORT/{}/'.format(Wayback.PORT),
                 '-e', 's/PROXY_PORT/{}/'.format(proxy_port),
                 resource_path('replay-proxy-nginx.conf')])
            conf_file = open(
                'replay-proxy-for-{}.conf'.format(
                    site_container.name), 'w')
            conf_file.write(conf_string.decode())
            conf_file.close()

            proxy_container = client.containers.run(
                'nginx', detach=True, remove=True,
                name='replay-proxy', network=network.name,
                volumes={'{}/replay-proxy-for-{}.conf'.format(
                    os.getcwd(), site_container.name): {
                        'bind': '/etc/nginx/conf.d/'
                        'server.conf', 'mode': 'ro'}
                }, ports={'{}/tcp'.format(proxy_port): proxy_port})
            register(proxy_container)

            driver = Driver.new_replay_driver()
            driver.start()
            register(driver)
            driver.replay("http://{}".format(replay_server_name))
        input("Press Enter to quit")
    finally:
        if network:
            network.disconnect(site_container)
            if pywb_container is not None:
                try:
                    network.disconnect(pywb_container)
                except docker.errors.NotFound:
                    pass
            if not args.standalone and proxy_container is not None:
                try:
                    network.disconnect(proxy_container)
                except docker.errors.NotFound:
                    pass
                except docker.errors.NullResource:
                    pass
            network.remove()
        subprocess_manager.shutdown()

    cleanup(args)
    sys.exit(0)


def setup(parser, **kwargs):
    """Records site assets to a warc file and playbacks the site

    You will need Docker to be installed on your machine.

    record                  Generate the warc and add it to the .rpz

    playback                  Playback the site using the warc.
                            (includes reprounzip docker run)

    For example:

        $ reprounzip dj record my_data_journalism_site.rpz target [--port]
        $ reprounzip dj playback my_data_journalism_site.rpz target [--port]

    """
    subparsers = parser.add_subparsers(title="actions",
                                       metavar='', help=argparse.SUPPRESS)

    for mode in ['playback', 'record', 'live-record']:
        parser = subparsers.add_parser(mode)
        parser.set_defaults(func=globals()[mode.replace("-", "_")])
        if mode == 'live-record':
            parser.add_argument('url', nargs=1,
                                help="URL of the site to record")
        else:
            parser.add_argument('pack', nargs=1, help="RPZ file")

        if mode == 'playback':
            parser.add_argument('--standalone', action='store_true',
                                help="run in webserver mode and view in "
                                "any browser")
            parser.add_argument('--hostname', nargs=1, help="specify the "
                                "hostname for the proxy server")

        parser.add_argument('target', nargs=1, help="target "
                            "directory")
        parser.add_argument('--port', dest='port',
                            help="webserver port",
                            default=80)
        parser.add_argument('--skip-setup', action='store_true',
                            help="skip reprounzip setup")
        parser.add_argument('--skip-run', action='store_true',
                            help="skip reprounzip run")
        parser.add_argument('--skip-destroy', action='store_true',
                            help="Keep reprozip docker "
                            "image, container, and target "
                            "dir after recording or playback")
        if mode == 'record':
            parser.add_argument('--skip-record',
                                action='store_true',
                                help="Simply write WARC data from "
                                "<target> back to <pack>")
        if mode == 'record' or mode == 'live-record':
            parser.add_argument('--keep-browser', action='store_true',
                                help="Keep the Chromium "
                                "browser open for manual recording")
        parser.add_argument('--quiet', action='store_true', help="shhhhhhh")
