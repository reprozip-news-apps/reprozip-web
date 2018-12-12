import os
import time
import pychrome
import yaml
import subprocess
import requests

config_file = open('config.yml', 'r')
config = yaml.load(config_file)

PROXY_HOST = 'localhost'
PROXY_PORT = os.getenv('PROXY_PORT')
WAYBACK_PORT = os.getenv('WAYBACK_PORT')
REPLAY_SERVER_NAME = os.getenv('REPLAY_SERVER_NAME')
CHROME_EXEC = config['CHROMIUM_EXEC']
CDP_PORT = '9222'

def cdp_url():
    return "http://localhost:{}".format(CDP_PORT)

def main():
    subprocess.Popen([CHROME_EXEC, '--proxy-server=http={}:{};https={}:{}'.format(PROXY_HOST, PROXY_PORT, PROXY_HOST, WAYBACK_PORT), '--remote-debugging-port={}'.format(CDP_PORT), '--ignore-certificate-errors'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    while True:
        try:
            res = requests.get(cdp_url())
            break
        except Exception as e:
            time.sleep(1)
            print("Waiting for browser to respond on port 9222")

    if res.status_code != 200:
        raise Exception("Bad status code from Chrome: {}".format(res.status_code))

    browser = pychrome.Browser(url=cdp_url())
    tab = browser.new_tab()
    tab.start()
    tab.call_method("Network.enable")
    tab.call_method("Page.navigate", url="http://{}".format(REPLAY_SERVER_NAME), _timeout=5)

main()
