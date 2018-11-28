#!/bin/sh

trap ' ' INT
python3 -m http.server 8000
trap - INT

echo "Goodbye"
