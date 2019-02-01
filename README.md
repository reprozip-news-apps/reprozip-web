# Prototype News Archiving App

A work-in-progress app that leverages ReproZip and Webrecorder to capture archival packages of data journalism websites.

## Prerequisites

You will need to install the Docker server and have it running on your system. See `https://docs.docker.com`

You will also need python3 and pip. One way to do this is using Pyenv. For example, on OSX (using Homebrew):

```
brew install pyenv
```

## Development Install

At some point the app will likely be installed from a registry, like most Python libraries. For now, it must be
installed from a local directory.

Recommendation: Use pyenv and virtualenv (or pipenv) to create a self-contained virtual environment:

```
$ pyenv local 3.7
$ pip install virtualenv
$ virtualenv .
$ source bin/activate
```

Now clone the repo and cd into it:

```
$ git clone https://github.com/reprozip-news-apps/reprozip-news-apps
$ cd reprozip-news-apps
```

Now install dependencies and the app into your virtualenv. Note that reprounzip-docker must be installed from
Github for now.

```
$ pip install -r requirements.txt
$ pip install -e .
```

## Step 1: Package a site using ReproZip

Skip to step 2 if you already have an RPZ package.

First run reprozip trace. For example (on Linux):

```
$ cd example
$ reprozip trace .
```
See reprozip documentation for more information on creating an RPZ.

## Step 2: Record the site assets from the RPZ using Webrecorder

You need an RPZ package and you need to know what port the packaged application runs on.

For example:

```
reprounzip dj record dollar4docs-20170309.rpz target --port 3000
```

You should see the WARC_DATA directory in the package now. For example:

```
$ tar -t -f dollar4docs-20170309.rpz
-rw-------  0 root   root 729415801 Mar  9  2017 DATA.tar.gz
-rw-------  0 root   root        19 Mar  9  2017 METADATA/version
-rw-r--r--  0 root   root   5912576 Mar  9  2017 METADATA/trace.sqlite3
-rw-------  0 root   root    293142 Mar  9  2017 METADATA/config.yml
-rw-r--r--  0 hoffman staff   807498 Jan 11 09:16 WARC_DATA/rec-20190111141622981410-anything.local.warc.gz
-rw-r--r--  0 hoffman staff    37089 Jan 11 09:16 WARC_DATA/autoindex.cdxj
```

## Step 3: Replay the site and verify fidelity

```
$ reprounzip dj playback dollar4docs-20170309.rpz target --port 3000
```

Now tab to your Chromium browser, turn off your wifi, and hit reload! Press Enter in your terminal session to
shut everything down.

## Skipping reprounzip unpacking on subsequent runs

The app should shut down everything except the docker container running the rpz'd site.

You can stop it yourself or just reuse it for subsequent playbacks and records:

```
$ reprounzip dj playback dollar4docs-20170309-2.rpz target --port 3000 --skip-setup --skip-run
```

## Packing and Recording Simultaneously

You can run reprozip trace and record at the same time, using two different terminals
(both on the site host, or one on the site host and one on a different host).

Terminal 1:

```
$ cd /path/to/your/project
$ reprozip trace .runserver
```

Terminal 2:

```
$ mkdir /path/to/target
$ reprounzip dj live-record http://localhost:3000 /path/to/target
```

Wait for the recorder to finish, then go back to Terminal 1 and press CTRL-C.

Terminal 1:

```
$ reprozip pack /path/to/captured-site.rpz
```

The final step is to merge the recorded data into the reprozip package:

```
$ reprounzip dj record /path/to/captured-site.rpz /path/to/target --skip-record
```
