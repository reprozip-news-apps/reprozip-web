# Prototype News Archiving App

A work-in-progress app that leverages ReproZip and Webrecorder to capture archival packages of data journalism websites.

## Prerequisites

You will need to install the Docker server and have it running on your system. For example, on OSX:

```
brew install docker
```

You will also need python3 and pip.

## Install

Install pipenv:

```
$ pip install pipenv
```

Install the project's dependencies:

```
$ pipenv install
```

## Bootstrap

Download a browser client for the recording service and initialize your config file:

```
$ ./scripts/bootstrap.sh
```

## Package a Site Using ReproZip

For example:

```
$ ./scripts/pack-hello-mars.sh
```

## Record the Site Using Webrecorder

For example:

```
$ ./scripts/record-rpz.sh hello-mars/hello-mars-20185814T155819.rpz 8000
```

You should see the WARC file in the package now:

```
$ tar -t -f hello-mars/hello-mars.rpz
```

## Caveats

Your mileage may vary. You may need to authorize the Chrome instance on your machine the first time it runs.
