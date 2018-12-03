#!/bin/bash

CWD=$(pwd)
TMP_DIR="$(dirname $0)/../tmp"

function usage {
    echo "Usage: $0 [record|replay|cleanup] <rpz_filepath> <port>"
}

if [ ! $1 ]; then
    usage && exit
fi

if [ "$1" = "cleanup" ]; then
    echo "shutting down services"

    docker stop replay-proxy

    # stop the unpacked site
    echo "Please manually stop docker container running on $PORT"
    docker ps
    exit
fi

if [ ! $2 ] || [ ! $3 ]; then
    usage && exit
fi


RPZ_FILE="$CWD/$2"
PORT=$3
NAME=${RPZ_FILE%%.*}
NAME=${NAME##*/}
UNPACK_DIR=$TMP_DIR/$NAME
TARGET_HOST=http://localhost

if [ ! -e $RPZ_FILE ]; then
   echo "Can't find: $RPZ_FILE"
   exit 0
fi

if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "There is already something running on port $PORT!"
    echo "Hint: docker ps"
    exit 0
fi

if [ ! -d $TMP_DIR ]; then
    mkdir $TMP_DIR
fi

# unpack RPZ
if [ ! -d $UNPACK_DIR ]; then
    reprounzip docker setup $RPZ_FILE $UNPACK_DIR
else
    echo "Warning: ReproUnzip target directory already exists: $UNPACK_DIR"
    sleep 3
    echo "Proceeding with existing target..."
fi

reprounzip docker run --detach --expose-port $PORT:$PORT $UNPACK_DIR

while ! curl -I $TARGET_HOST:$PORT | grep -m1 'HTTP/1.1 200 OK'; do
    echo "Waiting for 200 response from the target"
    sleep 5
done

case "$1" in
    record)
        wayback --record --live -a --auto-interval 5 &> wayback.out &
        WB_PID=$!
        cd $CWD

        while ! grep -m1 'Starting Gevent Server on 8080' < $TMP_DIR/wayback.out; do
            echo "waiting for wayback recorder to start"
            sleep 5
        done

        export TARGET_URL="http://localhost:$PORT"
        export COLLECTION_NAME=$NAME
        export PYWB_URL="http://localhost:8080"

        trap "{ kill $WB_PID; echo 'Wayback server did not shut down properly'; rm -rf $UNPACK_DIR; exit 1; }" SIGINT SIGTERM
        python3 recorder.py

        while ! grep -m1 'Auto-Indexing\.\.\.' < $TMP_DIR/wayback.out; do
            echo "waiting for wayback to write the WARC"
            sleep 1
        done

        kill $WB_PID
        LATEST_WARC=$(ls $TMP_DIR/collections/$NAME/archive/*.warc.gz | sort -V | tail -n 1)
        tar -r -f $RPZ_FILE -C ${LATEST_WARC%/*} ${LATEST_WARC##*/}
        echo "Done Recording:"
        tar -t -f $RPZ_FILE
        ;;

    replay)
        # extract the WARC file to tmp
        tar -xf $RPZ_FILE -C $TMP_DIR/collections/$NAME/archive rec*warc.gz
        LATEST_WARC=$(ls $TMP_DIR/collections/$NAME/archive/*.warc.gz | sort -V | tail -n 1)

        echo $LATEST_WARC

        PROXY_PIDFILE=$TMP_DIR/proxy.server.pid

        if [ -e "$PROXY_PIDFILE" ]; then
            pid=`cat $PROXY_PIDFILE 2>/dev/null`

            if [ "$pid" != "" ] && kill -0 $pid &>/dev/null; then
                echo "There already seems to be a proxy running (PID: $pid)"
                exit
            fi
        fi

        export PROXY_HOST=127.0.0.1
        export PROXY_PORT=8888
        export SITE_URL=http://news-app.com

        if lsof -Pi :$PROXY_PORT -sTCP:LISTEN -t >/dev/null ; then
            echo "There is already something running on port $PORT!"
            exit
        fi

        # start proxy server
        docker run --rm --detach --name replay-proxy -v $(pwd)/replay-proxy-nginx.conf:/etc/nginx/conf.d/server.conf:ro -p $PROXY_PORT:80

        # start player
        # trap "{ kill $PROXY_PID; echo 'Stopping proxy server'; exit 1; }" SIGINT SIGTERM
        python3 replayer.py

        exit
        ;;
    *)
        usage && exit
        ;;

esac
