import base64
import gzip
import json
from collections import defaultdict
from datetime import datetime
from uuid import uuid4

import structlog

logger = structlog.get_logger(__name__)


def chunk_string(string: str, chunk_length: int):
    return [string[0 + offset : chunk_length + offset] for offset in range(0, len(string), chunk_length)]


try:
    with open("clickhouseRecordingEvents.json", "r") as myfile:
        data = myfile.read()
except FileNotFoundError:
    logger.error(
        "`clickhouseRecordingEvents.json` not found. Read the 'Prep Data' section of the README for instructions."
    )
    exit(1)

logger.info("Prepping data for the load test. This may take a while...")

raw_data = json.loads(data)

chunk_collector = defaultdict(list)


for row in raw_data:
    snapshot_data = json.loads(row["snapshot_data"])
    data = {
        **row,
        **snapshot_data,
    }
    del data["snapshot_data"]

    chunk_collector[snapshot_data["chunk_id"]].append(data)

kafka_events = []

skipped_chunk_count = 0

min_created_at = datetime.fromisoformat(
    min(raw_data, key=lambda x: datetime.fromisoformat(x["created_at"]))["created_at"]
).timestamp()

for chunk_id, data_rows in chunk_collector.items():
    expected_chunk_count = data_rows[0]["chunk_count"]
    if len(data_rows) != expected_chunk_count:
        # This case will be hit because the time boundaries of the clickhouse query can split chunks
        skipped_chunk_count += 1
        continue
    sorted_data_rows = sorted(data_rows, key=lambda x: x["chunk_index"])
    compressed_base_64_data = ""
    for row in sorted_data_rows:
        compressed_base_64_data += row["data"]
    compressed_bytes = base64.b64decode(compressed_base_64_data)
    decompressed_data = gzip.decompress(compressed_bytes).decode("utf-16", "surrogatepass")

    events = json.loads(decompressed_data)
    session_id = data_rows[0]["session_id"]
    window_id = data_rows[0]["window_id"]
    distinct_id = data_rows[0]["distinct_id"]
    team_id = data_rows[0]["team_id"]
    created_at = datetime.fromisoformat(data_rows[0]["created_at"]).timestamp()
    for event in events:
        chunked_event_data = chunk_string(json.dumps(event), 512 * 1024)
        event_uuid = str(uuid4())
        for index, chunk in enumerate(chunked_event_data):
            kafka_events.append(
                {
                    "headers": {
                        "unixTimestamp": event["timestamp"],
                        "eventId": event_uuid,
                        "sessionId": session_id,
                        "windowId": window_id,
                        "distinctId": distinct_id,
                        "chunkIndex": index,
                        "chunkCount": len(chunked_event_data),
                        "teamId": team_id,
                        "eventSource": event.get("data", {}).get("source"),
                        "eventType": event.get("type"),
                    },
                    "value": chunk,
                    "timestampOffset": created_at - min_created_at,
                }
            )


sorted_kafka_events = sorted(kafka_events, key=lambda x: (x["timestampOffset"], x["headers"]["chunkIndex"]))

with open("kafkaEvents.txt", "w") as file:
    for event in sorted_kafka_events:
        file.write(json.dumps(event) + "\n")

logger.info(
    "Processed {} events, skipped {} chunks, created {} kafka events".format(
        len(raw_data), skipped_chunk_count, len(kafka_events)
    )
)
