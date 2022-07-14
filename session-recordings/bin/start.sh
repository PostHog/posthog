#!/bin/sh

set -e

# Start both the api and the ingester in the background
node ./dist/api.js &
node ./dist/ingester/index.js &

# Wait for any process to exit
wait -n

# Exit with the status code of the command that exited
exit $?
