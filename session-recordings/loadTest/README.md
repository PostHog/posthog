# Recording ingestion load test

This is a simple load test for the recording ingestion service. It allows you to send production level loads at the ingester to see how it performs.

## Data prep

The first step to to prepare recording data for the ingester. To do this, you need to run a query like the following in metabase.

`SELECT * FROM session_recording_events WHERE timestamp > now() - INTERVAL 10 MINUTE and timestamp < now()`

Export the results of this query as a JSON file and save it to a file named `clickhouseRecordingEvents.json` in this folder. (This file is included in the .gitignore file so it is not committed to the repository.)

Then you can run the data prep script in this folder using `python prep_data.py`.

This script creates a file named `kafkaEvents.txt` that contains a list of JSON objects that represent the data from the query above in the format that it would have been sent to the ingester.

## Run the load test

Once the `kafkaEvents.txt` file is created, you're ready to start the load test. First, you'll want to make sure:

-   Kafka is running
-   The ingester is running

Next, you can start producing events to the Kafka topic by using the following command: `python run_load_test.py`.

This produces events to the kafka queue as they would have been sent by `capture.py`. In addition to making the data consistent, it also tries to mimic the timing that the events were sent.
