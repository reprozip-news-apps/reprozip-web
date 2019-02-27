ReproZip News App Archiving Tool's Documentation
================================================

Welcome to ReproZip News App Archiving Tool's documentation!
This tool is a prototype that leverages `ReproZip <https://www.reprozip.org/>`_ and `Webrecorder <https://webrecorder.io/>`_ to archive data journalism news apps and allows users to replay these apps with little to no effort.

=========================
Installation Instructions
=========================

Python 2.7.3 or greater, or 3.3 or greater is required. If you don't have Python on your machine, you can get it from `python.org <https://www.python.org/>`__. You will also need the `pip <https://pip.pypa.io/en/latest/installing/>`__ installer and `Docker <https://www.docker.com/>`__.

For Debian and Ubuntu, you can get most of the required dependencies using APT::

    apt-get install python python-dev python-pip

For Fedora and CentOS, you can get most of the dependencies using the Yum packaging manager::

    yum install python python-devel

For macOS, be sure to upgrade `setuptools`::

    $ pip install -U setuptools

After installing these required dependencies, clone the repository and cd into it::
	
	$ git clone https://github.com/reprozip-news-apps/reprozip-news-apps
	$ cd reprozip-news-apps
	
Now install all the dependencies and the prototype::

	$ pip install -r requirements.txt
	$ pip install -e .

==================================
Archiving and Replaying a News App
==================================

-------------------------------------
Step 1: Package a site using ReproZip
-------------------------------------

Skip to step 2 if you already have an ``.rpz`` package. Otherwise, follow the `ReproZip's documentation <https://reprozip.readthedocs.io/en/1.0.x/packing.html>`_ to package a news app using ReproZip.

-----------------------------------------------------------------
Step 2: Record the site assets from the package using Webrecorder
-----------------------------------------------------------------

Make sure that you have Docker installed and running. Given an `.rpz` package from a news app, you can run the following command::

	reprounzip dj record <package> <target> --port <port>

where ``<package>`` is the ``.rpz`` file, ``<target>`` is the target directory for ReproZip, and ``<port>`` is the port number where the news app run. For instance, a Rails app will likely run on port ``3000``, while a NodeJS app will likely run on port ``8000``.

You should be able to see the ``WARC_DATA`` directory in the package now::

	$ tar -t -f <package>
	-rw-------  0 root   root 729415801 Mar  9  2017 DATA.tar.gz
	-rw-------  0 root   root        19 Mar  9  2017 METADATA/version
	-rw-r--r--  0 root   root   5912576 Mar  9  2017 METADATA/trace.sqlite3
	-rw-------  0 root   root    293142 Mar  9  2017 METADATA/config.yml
	-rw-r--r--  0 hoffman staff   807498 Jan 11 09:16 WARC_DATA/rec-20190111141622981410-anything.local.warc.gz
	-rw-r--r--  0 hoffman staff    37089 Jan 11 09:16 WARC_DATA/autoindex.cdxj


---------------------------
Step 3: Replay the news app
---------------------------

To replay the package news app, run the following command::

	$ reprounzip dj playback <package> <target> --port <port>
	
Now you can go to your Chromium browser, turn off your Wi-Fi, and hit reload. Press Enter in your terminal session to shut everything down.

-----------------------------
Skipping removal of container
-----------------------------

When you finish recording, or exit a playback session, the unpacked container will be automatically destroyed. You can prevent this from happening by using the ``--skip-destroy`` flag::

	$ reprounzip dj playback <package> <target> --port <port> --skip-destroy

Then you can reuse the container on another playback session::

	$ reprounzip dj playback <package> <target> --port <port> --skip-setup --skip-run

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
=======

