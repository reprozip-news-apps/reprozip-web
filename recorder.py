import os
from collections import deque
import subprocess
import requests
import time
import pychrome
import yaml

config_file = open('config.yml', 'r')
config = yaml.load(config_file)

PYWB_URL = os.getenv('PYWB_URL', 'http://localhost:8080')
WB_COLLECTION = os.getenv('COLLECTION_NAME')
CHROME_EXEC = config['CHROMIUM_EXEC']
CDP_PORT = '9222'
TARGET_URL = os.getenv('TARGET_URL')

url_queue = deque()

def cdp_url():
    return "http://localhost:{}".format(CDP_PORT)

def main():
    #start browser and ensure CDP
    subprocess.Popen([CHROME_EXEC, '--remote-debugging-port={}'.format(CDP_PORT)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    while len(url_queue):
        record_next_url(browser);

    print("all done");

def record_next_url(browser):
    url_to_visit = url_queue[0]
    print("Recording {}".format(url_to_visit))
    record_url = "{}/{}/record/{}".format(PYWB_URL, WB_COLLECTION, url_to_visit)
    tab = browser.new_tab()
    tab.start()
    tab.call_method("Network.enable")
    tab.call_method("Page.navigate", url=record_url, _timeout=5)
    tab.wait(5)
    tab.stop()

    browser.close_tab(tab)
    url_queue.popleft()

url_queue.append(TARGET_URL)
main()
