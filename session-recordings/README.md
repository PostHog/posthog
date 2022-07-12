# Session Recordings persistence

Responsible for writing Session Recordings from the main event ingestion topic
into S3 (or compatible) for persistence, as well as exposing recordings via an
HTTP API.

## Components

Ingester - reads off of the event ingestion topic, filtering down to only the
`$snapshot` events, partitioning these by `(team_id, session_id, window_id)` and
writing these as chunks to S3.

API - given a `(team_id, session_id)` pair, returns the corresponding events as
a paginated list.

## Dependencies

The keep complexity down, we are only dependent on Kafka and MinIO.

## Development

To get up and running with tests, have the following commands running:

```bash
docker-compose up
yarn start
yarn test
```
