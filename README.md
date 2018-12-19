# Prototype News Archiving App

A work-in-progress app that leverages ReproZip and Webrecorder to capture archival packages of data journalism websites.

## Prerequisites

You will need to install the Docker server and have it running on your system. For example, on OSX:

```
brew install docker
```

You will also need python3 and pip.

## Development Install

Install pipenv:

```
$ pip install pipenv
```

Create a virtual environment

```
$ pipenv --python 3.7.1
```

Install dependencies

```
pipenv install
```

Install the app/package

```
$ pip install -e .
```

Start the virtual env shell:

```
pipenv shell
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
reprounzip dj hello-mars/hello-mars-20185814T155819.rpz target 8000
```

You should see the WARC file in the package now:

```
$ tar -t -f hello-mars/hello-mars-20185814T155819.rpz
```

## Replay the site and verify fidelity

```
$ ./scripts/rpz-player.sh replay hello-mars 8000
```
Now tab to your Chromium browser, turn off your wifi, and hit reload!

## Caveats

Your mileage may vary. You may need to authorize the Chromium instance on your machine the first time it runs.
