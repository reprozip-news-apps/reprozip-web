.. reprozip-news-app documentation master file, created by
   sphinx-quickstart on Sun Feb 17 13:59:40 2019.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to reprozip-news-app's documentation!
=============================================

Here is an introduction for how to use reprounzip

1. Introduction
2. Prerequisites
3. Development Install

============================
Prototype News Archiving App
============================

A work-in-progress app that leverages ReproZip and Webrecorder to capture archival packages of data journalism websites.

=============
Prerequisites
=============

You will need to install the Docker server and havie it running on your system. See `this link <https://docs.docker.com>`_.

You will also nedd Python 3 and pip. One way to do this is using Pyenv. For example, on OSX command line (using `Homebrew <https://brew.sh/>`_)::

	brew install pyenv

On Debian/Ubuntu::

	sudo apt install python3.7 python3.7-dev virtualenv docker.io

===================
Development Install
===================

At some point the app will likely be installed from a registry, like most Python libraries. For now, it must be installed from a local directory.

Recommendation: Use pyenv and virtualenv (or pipenv) to create a self-contained virtual environment::

	$ pyenv local 3.7
	$ pip install virtualenv
	$ virtualenv .
	$ source bin/activate
	
Note that the port number will depend on the webserver you captured in step 1. A Rails app will likely run on port 3000, a NodeJS app will likely run on port 8000.

Now clone the repo and cd into it::
	
	$ git clone https://github.com/reprozip-news-apps/reprozip-news-apps
	$ cd reprozip-news-apps
	
Now install dependencies and the app into your virtualenv. Note that reprounzip-docker must be installed from Github for now.::

	$ pip install -r requirements.txt
	$ pip install -e .
		
In case you met error called "Found existing installation", you can run above command as ::

	$ pip install -r requirements.txt --ignore-installed
	$ pip install -e .
	

====================
Archiving a news app
====================

Below is an instruction to pack and unpack a news app from `ProPublica <https://www.propublica.org/>`_

-------------------------------------
Step 1: Package a site using ReproZip
-------------------------------------

Skip to step 2 if you already have an RPZ package. Otherwise, see `reprozip documentation:
<https://reprozip.readthedocs.io/en/1.0.x/packing.html>`_. Reprozip only runs on Linux.

-----------------------------------------------------------
Step 2: Record the site assets from the RPZ using Webrecord
-----------------------------------------------------------

You need an RPZ package and you need to know what port the packaged application runs on. Please make sure that docker is running
and the port you want to use is available.

You can check if docker is running by ::

	docker ps
	
This command will return ``Cannot connect to the Docker daemon`` if docker is running. Otherwise, it will return a table that lists all docker container.
To stop a container at certain port ::

	docker stop container_id

For example::

	reprounzip dj record dollar4docs-20170309.rpz target --port 3000

Note that the port number will depend on the webserver you captured in step 1. A Rails app will likely run on port 3000, a NodeJS app will likely run on port 8000.

You should see the WARC_DATA directory in the package now. For example::

	$ tar -t -f dollar4docs-20170309.rpz
	-rw-------  0 root   root 729415801 Mar  9  2017 DATA.tar.gz
	-rw-------  0 root   root        19 Mar  9  2017 METADATA/version
	-rw-r--r--  0 root   root   5912576 Mar  9  2017 METADATA/trace.sqlite3
	-rw-------  0 root   root    293142 Mar  9  2017 METADATA/config.yml
	-rw-r--r--  0 hoffman staff   807498 Jan 11 09:16 WARC_DATA/rec-20190111141622981410-anything.local.warc.gz
	-rw-r--r--  0 hoffman staff    37089 Jan 11 09:16 WARC_DATA/autoindex.cdxj


-------------------------------------------
Step 3: Replay the site and verify fidelity
-------------------------------------------

Run command ::

	$ reprounzip dj playback dollar4docs-20170309.rpz target --port 3000
	
Now tab to your Chromium browser, turn off your wifi, and hit reload! Press Enter in your terminal session to shut everything down.

------------------------------------------------
Skipping reprounzip unpacking on subsequent runs
------------------------------------------------

When you finish recording, or exit a playback session, the unpacked container will be destroyed. You can prevent that from happening by using the --skip-destroy flag::

	$ reprounzip dj playback dollar4docs-20170309.rpz target --port 3000 --skip-destroy

Then you can reuse the container on another playback session::

	$ reprounzip dj playback dollar4docs-20170309.rpz target --port 3000 --skip-setup --skip-run


=====
Flags
=====
:code:`--standalone`

:code:`--port`

:code:`--skip-setup`

:code:`--skip-run`

:code:`--skip-destroy`

:code:`--skip-record`

:code:`--keep-browser`

:code:`--quiet`




.. toctree::
   :maxdepth: 2
   :caption: Contents:



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
