#!/bin/bash

cd "$(dirname $0)/../example/hello-mars"

docker build -t savingdatajournalism/hello-mars .

docker run --rm --cap-add=SYS_PTRACE --name packing-hello-mars -v $(pwd):/hello-mars savingdatajournalism/hello-mars /bin/bash -c "cd /hello-mars && reprozip pack hello-mars-$(date "+%Y%M%dT%H%M%S")"

