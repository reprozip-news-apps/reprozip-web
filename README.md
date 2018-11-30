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

## Package a site using ReproZip

First run reprozip trace. For example (on Linux):

```
$ cd example/hello-mars
$ reprozip trace .
```

(You can skip the trace step if you just want to run the sample)

Now pack it.

```
$ reprozip pack hello-mars
```

To pack the example in a non-Linux environment (i.e., for testing),
you can just do this:

```
$ ./scripts/pack-hello-mars.sh
```
You should see a new .rpz file in the example directory.


## Record the site using Webrecorder

For example:

```
$ ./scripts/record-rpz.sh hello-mars/hello-mars-20185814T155819.rpz 8000
```

You should see the WARC file in the package now:

```
$ tar -t -f hello-mars/hello-mars-20185814T155819.rpz
```

## Replay the site and verify fidelity

This work is currently in progress.

## Caveats

Your mileage may vary. You may need to authorize the Chromium instance on your machine the first time it runs.
