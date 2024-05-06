# [Deprecated — see https://web.reprozip.org] Prototype Web Archiving App

A 2018 prototype of ReproZip-Web (see current: https://web.reprozip.org/) that leverages ReproZip and Webrecorder to capture archival packages of data journalism websites. Deprecated in 2021.

## Prerequisites

You will need to install the Docker server and have it running on your system. See `https://docs.docker.com`

You will also need python3 and pip. One way to do this is using Pyenv. For example, on OSX (using Homebrew):

```
brew install pyenv
```

On Debian/Ubuntu:

```
sudo apt install python3.7 python3.7-dev virtualenv docker.io
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
$ git clone https://github.com/reprozip-news-apps/reprozip-web
$ cd reprozip-web
```

Now install dependencies and the app into your virtualenv. Note that reprounzip-docker must be installed from
Github for now.

```
$ pip install -r requirements.txt
$ pip install -e .
```

## Step 1: Package a site using ReproZip

Skip to step 2 if you already have an RPZ package. Otherwise, see reprozip documentation:

https://reprozip.readthedocs.io/en/1.0.x/packing.html

## Step 2: Record the site assets from the RPZ using Webrecorder

You need an RPZ package and you need to know what port the packaged application runs on.

For example:

```
reprounzip dj record web-app.rpz target --port 3000
```

Note that the port number will depend on the webserver you captured in step 1. A Rails app
will likely run on port 3000, a NodeJS app will likely run on port 8000.

You should see the WARC_DATA directory in the package now. For example:

```
$ tar -t -f web-app.rpz
-rw-------  0 root   root 729415801 Mar  9  2017 DATA.tar.gz
-rw-------  0 root   root        19 Mar  9  2017 METADATA/version
-rw-r--r--  0 root   root   5912576 Mar  9  2017 METADATA/trace.sqlite3
-rw-------  0 root   root    293142 Mar  9  2017 METADATA/config.yml
-rw-r--r--  0 hoffman staff   807498 Jan 11 09:16 WARC_DATA/rec-20190111141622981410-anything.local.warc.gz
-rw-r--r--  0 hoffman staff    37089 Jan 11 09:16 WARC_DATA/autoindex.cdxj
```

## Step 3: Replay the site and verify fidelity

```
$ reprounzip dj playback web-app.rpz target --port 3000
```

Now tab to your Chromium browser, turn off your wifi, and hit reload! Press Enter in your terminal session to
shut everything down.

## Skipping reprounzip unpacking on subsequent runs

When you finish recording, or exit a playback session, the unpacked container will be destroyed. You can prevent
that from happening by using the `--skip-destroy` flag:

```
$ reprounzip dj playback web-app.rpz target --port 3000 --skip-destroy
```

Then you can reuse the container on another playback session:

```
$ reprounzip dj playback web-app.rpz target --port 3000 --skip-setup --skip-run
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

## Using Wayback as a standalone frontend

If you don't want to use a bespoke browser, or want to share an archive over the web,
you can use the `--standalone` flag to play the site back like any other WARC collection:

```
$ reprounzip dj playback web-app.rpz target --port 3000 --standalone
$ curl http://localhost:8080/http://web-app.rpz
```

