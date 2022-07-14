#!/bin/sh

# The test command we run in CI

set -e

# Start up any service dependencies
docker-compose up -d

# Bring up the ingester/server in the background. Locally if you want to test
# this out, build the image with a tag of `session-recordings`
CONTAINER_NAME=session-recordings-test
trap 'docker kill $(docker ps -q --filter="name=$CONTAINER_NAME")' EXIT
docker run --rm \
  -e OBJECT_STORAGE_ACCESS_KEY_ID=root \
  -e OBJECT_STORAGE_SECRET_ACCESS_KEY=password \
  -e OBJECT_STORAGE_ENDPOINT=http://localhost:19000 \
  -e MAX_EVENT_GROUP_AGE=1000 \
  -e MAX_EVENT_GROUP_SIZE=1000 \
  --network host \
  --name $CONTAINER_NAME \
  "${1:-session-recordings}" &

# Wait for the ingester to be up
until (curl --silent http://localhost:3001/metrics);
do
  echo "Waiting for instance to come up"
  sleep 5
done

# Run the tests
yarn test run
