# Prototype News Archiving App

A work-in-progress app that leverages ReproZip and Webrecorder to capture archival packages of data journalism websites.

## Prerequisites

You will need to install the Docker server and have it running on your system. For example, on OSX:

```
brew install docker
```

You will also need python3 and pip.

## Development Install

Clone the repo:

```
$ git clone https://github.com/reprozip-news-apps/reprozip-news-apps
$ cd reprozip-news-apps
```

Recommendation: Use pipenv (or virtualenv) to create a virtual environment

```
$ pip install pipenv
$ pipenv --python 3.7.1
$ pipenv shell
```

Install dependencies

```
$ pip install -r requirements.txt
```

Install the app

```
$ pip install -e .
```

## Package a site using ReproZip

First run reprozip trace. For example (on Linux):

```
$ cd example
$ reprozip trace .
```

## Record the site using Webrecorder

For example:

```
reprounzip dj record dollar4docs-20170309-2.rpz target --port 3000
```

You should see the WARC file in the package now:

```
$ tar -t -f hello-mars/hello-mars-20185814T155819.rpz
```

## Replay the site and verify fidelity

```
$ reprounzip dj playback dollar4docs-20170309-2.rpz target --port 3000
```
Now tab to your Chromium browser, turn off your wifi, and hit reload!

## Skipping reprounzip unpacking on subsequent runs

The app should shut down everything except the docker container running the rpz'd site.

You can stop it yourself or just reuse it for subsequent playbacks and records:

```
$ reprounzip dj playback dollar4docs-20170309-2.rpz target --port 3000 --skip-setup --skip-run
```

