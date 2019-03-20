import io
import os
from setuptools import setup, find_packages

setup(name='reprozip-web',
      version='0.1',
      packages=['reprounzip', 'reprounzip.unpackers'],
      entry_points={
          'reprounzip.unpackers': [
              'dj = reprounzip.unpackers.dj:setup']},
      namespace_packages=['reprounzip', 'reprounzip.unpackers'],
      install_requires=[
          'reprounzip>=1.0.10',
          'reprounzip-docker',
          'requests',
          'pywb',
          'pyppeteer',
          'pychrome',
          'docker'],
      description="Allows the ReproZip unpacker to record and replay web applications packaged as .rpz files")
