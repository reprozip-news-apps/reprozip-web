import os
import time
import pychrome
import yaml
import subprocess
import requests

config_file = open('config.yml', 'r')
config = yaml.load(config_file)

PROXY_HOST = os.getenv('PROXY_HOST')
PROXY_PORT = os.getenv('PROXY_PORT')
SITE_URL = os.getenv('SITE_URL')
CHROME_EXEC = config['CHROMIUM_EXEC']
CDP_PORT = '9222'

def cdp_url():
    return "http://localhost:{}".format(CDP_PORT)

def main():
    subprocess.Popen([CHROME_EXEC, '--proxy-server={}:{}'.format(PROXY_HOST, PROXY_PORT), '--remote-debugging-port={}'.format(CDP_PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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
    tab.call_method("Page.navigate", url=SITE_URL, _timeout=5)

main()
