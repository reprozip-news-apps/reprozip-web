#!/bin/bash

if [ ! -d "$(dirname $0)/../tmp" ]; then
    mkdir "$(dirname $0)/../tmp"
fi

cd "$(dirname $0)/../hello-mars"

LATEST_RPZ=$(ls *.rpz | sort -V | tail -n 1)
UNPACK_DIR=$(sed "s/\..*//" <<< $LATEST_RPZ)

if [ ! -d "$UNPACK_DIR" ]; then
    reprounzip docker setup $LATEST_RPZ $UNPACK_DIR
fi

reprounzip docker run --detach --expose-port 8000:8000 $UNPACK_DIR

if [ ! -d "collections" ]; then
    wb-manager init hello-mars
fi

wayback --record --live -a --auto-interval 5 &> ../tmp/wayback.out &

while ! grep -m1 'Starting Gevent Server on 8080' < ../tmp/wayback.out; do
    echo "waiting for wayback recorder to start"
    sleep 5
done

# insert automated browser here:
python3 ../chromium-pywb-client.py

while ! grep -m1 'Auto-Indexing\.\.\.' < ../tmp/wayback.out; do
    echo "waiting for wayback to write the WARC"
    sleep 1
done

kill %1
LATEST_WARC=$(ls collections/hello-mars/archive/*.warc.gz | sort -V | tail -n 1)
echo "DONE:"
echo "RPZ File: $LATEST_RPZ"
echo "WARC File: $LATEST_WARC"
