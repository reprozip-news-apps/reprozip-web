from pyppeteer import chromium_downloader
from pathlib import Path
import sys
import yaml
import os
import docker

if Path('config.yml').exists():
    print("Looks like config.yml has already been created - Exiting")
    sys.exit()

config = dict()

chromium_executable = chromium_downloader.chromium_executable()

if not chromium_executable.exists():
    print("Downloading Chromium browser")
    chromium_downloader.download_chromium()

print("Chromium browser located here: {}".format(str(chromium_executable)))

config['CHROMIUM_EXEC'] = str(chromium_executable)

stream = open('config.yml', 'w')
yaml.dump(config, stream)

print("Checking Docker server")
client = docker.from_env()
try:
    client.ping()
    print("Success!")
except Exception as e:
    print("Can't ping the docker server. Have you installed docker on this system?")
    raise e
