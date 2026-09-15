#!/bin/sh
set -eu
# Railway mounts the persistent volume as root. Prepare only its mount directory,
# then drop privileges before starting the API. Existing database files stay intact.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown agentguard:agentguard /data
    exec gosu agentguard "$@"
fi
exec "$@"
