FROM ubuntu:16.04

COPY busybox /busybox
COPY rpzsudo /rpzsudo

COPY data.tgz /reprozip_data.tgz

COPY rpz-files.list /rpz-files.list
RUN \
    chmod +x /busybox /rpzsudo && \
    cd / && (tar zpxf /reprozip_data.tgz -U --recursive-unlink --numeric-owner --strip=1 --null -T /rpz-files.list || /busybox echo "TAR reports errors, this might or might not prevent the execution to run")
