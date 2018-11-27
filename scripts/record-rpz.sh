#!/bin/bash

CWD=$(pwd)

# We need to know the port the reanimated site
# will run on. Perhaps this will be extractable from
# the .rpz at some point
if [ ! $1 ] || [ ! $2 ]; then
    echo "Usage: record-rpz.sh RPZ_FILEPATH PORT_TO_RECORD"
    exit 0
fi

RPZ_FILE="$CWD/$1"
PORT=$2
NAME=${RPZ_FILE%%.*}
NAME=${NAME##*/}
TMP_DIR="$(dirname $0)/../tmp"
UNPACK_DIR=$TMP_DIR/$NAME

if [ ! -e $RPZ_FILE ]; then
   echo "Can't find: $RPZ_FILE"
   exit 0
fi

if [ ! -d $TMP_DIR ]; then
    mkdir $TMP_DIR
fi

if [ ! -d $UNPACK_DIR ]; then
    reprounzip docker setup $RPZ_FILE $UNPACK_DIR
else
    echo "Directory already exists: $UNPACK_DIR"
    exit 0
fi

reprounzip docker run --detach --expose-port $PORT:$PORT $UNPACK_DIR

cd $TMP_DIR
if [ ! -d collections/$NAME ]; then
    wb-manager init $NAME
fi

wayback --record --live -a --auto-interval 5 &> wayback.out &
cd $CWD

while ! grep -m1 'Starting Gevent Server on 8080' < $TMP_DIR/wayback.out; do
    echo "waiting for wayback recorder to start"
    sleep 5
done

export TARGET_URL="http://localhost:$PORT"
export COLLECTION_NAME=$NAME
export PYWB_URL="http://localhost:8080"

python3 recorder.py

while ! grep -m1 'Auto-Indexing\.\.\.' < $TMP_DIR/wayback.out; do
    echo "waiting for wayback to write the WARC"
    sleep 1
done

kill %1
LATEST_WARC=$(ls $TMP_DIR/collections/$NAME/archive/*.warc.gz | sort -V | tail -n 1)
tar -r -f $RPZ_FILE -C ${LATEST_WARC%/*} ${LATEST_WARC##*/}
echo "Done Recording:"
tar -t -f $RPZ_FILE
