#!/bin/bash

CWD=$(pwd)
RPZ_TMP_DIR="$(cd $(dirname $0)/../tmp && pwd)"

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
UNPACK_DIR=$RPZ_TMP_DIR/$NAME
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

if [ ! -d $RPZ_TMP_DIR ]; then
    mkdir $RPZ_TMP_DIR
fi

# unpack RPZ
if [ ! -d $UNPACK_DIR ]; then
    reprounzip docker setup $RPZ_FILE $UNPACK_DIR
else
    echo "Warning: ReproUnzip target directory already exists: $UNPACK_DIR"
    sleep 3
    echo "Proceeding with existing target..."
fi

CONTAINER_ID=$(reprounzip docker run --detach --expose-port $PORT:$PORT $UNPACK_DIR)
CONTAINER_NAME=$(python3 -c "import subprocess, io, json; print(json.load(io.StringIO(subprocess.run(['docker', 'container', 'inspect', '$CONTAINER_ID'], capture_output=True).stdout.decode()))[0]['Name'][1:])")
echo "CONTAINER $CONTAINER_NAME"

while ! curl -I $TARGET_HOST:$PORT | grep -m1 'HTTP/1.1 200 OK'; do
    echo "Waiting for 200 response from the target (this may take a few minutes)"
    sleep 5
done

case "$1" in
    record)
        cd $RPZ_TMP_DIR
        if [ ! -d collections/$NAME ]; then
            wb-manager init $NAME
        fi

        wayback --record --live -a --auto-interval 5 &> wayback.out &
        WB_PID=$!
        cd $CWD

        while ! grep -m1 'Starting Gevent Server on 8080' < $RPZ_TMP_DIR/wayback.out; do
            echo "waiting for wayback recorder to start"
            sleep 5
        done

        export TARGET_URL="http://localhost:$PORT"
        export COLLECTION_NAME=$NAME
        export PYWB_URL="http://localhost:8080"

        trap "{ kill $WB_PID; echo 'Wayback server did not shut down properly'; rm -rf $UNPACK_DIR; exit 1; }" SIGINT SIGTERM
        python3 recorder.py

        while ! grep -m1 'Auto-Indexing\.\.\.' < $RPZ_TMP_DIR/wayback.out; do
            echo "waiting for wayback to write the WARC"
            sleep 1
        done

        kill $WB_PID
        LATEST_WARC=$(ls $RPZ_TMP_DIR/collections/$NAME/archive/*.warc.gz | sort -V | tail -n 1)
        tar -r -f $RPZ_FILE -C ${LATEST_WARC%/*} ${LATEST_WARC##*/}
        echo "Done Recording:"
        tar -t -f $RPZ_FILE
        ;;

    replay)
        REPLAY_SERVER_NAME=rpzdj-repl.ay
        # create docker network
        NETWORK_NAME=rpzdj_$(date "+%Y-%m-%d%H_%M_%S")
        NETWORK_ID=$(docker network create --attachable $NETWORK_NAME)

        echo "NETWORK $NETWORK_NAME"

        #put the container in the network
        docker network connect $NETWORK_NAME $CONTAINER_NAME

        # extract the WARC file to tmp
        tar -xf $RPZ_FILE -C $RPZ_TMP_DIR/collections/$NAME/archive rec*warc.gz
        LATEST_WARC=$(ls $RPZ_TMP_DIR/collections/$NAME/archive/*.warc.gz | sort -V | tail -n 1)

        echo $LATEST_WARC

        # run wayback
        export WAYBACK_PORT=8080

        wayback -p $WAYBACK_PORT --proxy $NAME -d $RPZ_TMP_DIR &> $RPZ_TMP_DIR/wayback.replay.out &

        while ! grep -m1 'Starting Gevent Server' < $RPZ_TMP_DIR/wayback.replay.out; do
            echo "waiting for wayback replay to start"
            sleep 5
        done


        # run the proxy
        export PROXY_PORT=8081

        sed -e "s/PROXIED_SERVER/$CONTAINER_NAME:$PORT/" -e "s/SERVER_NAME/$REPLAY_SERVER_NAME/" replay-proxy-nginx.conf> $RPZ_TMP_DIR/replay-proxy-for-$CONTAINER_NAME.conf

        if lsof -Pi :$PROXY_PORT -sTCP:LISTEN -t >/dev/null ; then
            echo "There is already something running on port $PORT!"
            exit
        fi

        docker run --rm --detach --name replay-proxy-$(date "+%Y-%m-%d%H_%M_%S") --network $NETWORK_NAME -v $RPZ_TMP_DIR/replay-proxy-for-$CONTAINER_NAME.conf:/etc/nginx/conf.d/server.conf:ro -p $PROXY_PORT:$PROXY_PORT nginx

        sleep 3

        python3 replayer.py

        exit
        ;;
    *)
        usage && exit
        ;;

esac
