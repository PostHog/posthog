import hashlib
import json
from time import time

import structlog
from kafka import KafkaProducer as KP

logger = structlog.get_logger(__name__)


producer = KP(retries=5, bootstrap_servers=["localhost"])
try:
    with open("kafkaEvents.txt", "r") as f:
        start = time()
        for line in f:
            event = json.loads(line)
            current_offset = time() - start

            while current_offset < event["timestampOffset"]:
                current_offset = time() - start

            logger.info("Sending event late by (seconds): {}".format(current_offset - event["timestampOffset"]))

            header_list = []
            for key, value in event["headers"].items():
                header_list.append((key, str(value).encode("utf-8")))

            producer.send(
                "recording_events",
                value=event["value"].encode("utf-8"),
                key=hashlib.sha256(event["headers"]["sessionId"].encode()).hexdigest().encode("utf-8"),
                headers=header_list,
            )
except FileNotFoundError:
    logger.error("`kafkaEvents.txt` not found. Please run `prep_data.py` first to generate this file.")
    exit(1)
