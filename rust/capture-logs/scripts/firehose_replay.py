#!/usr/bin/env python3
"""Send capture-logs a request it cannot tell apart from a real Firehose delivery.

Auth is one opaque header holding the project API key, and both payload layers are documented
JSON, so a laptop can exercise the endpoint without an AWS account. What this cannot reach is
Firehose's own behavior: its retry loop, its 3 minute deadline, and how strictly it parses our
response. Those need the live delivery test.

Stdlib only, so it runs against a dev stack without installing anything.

    ./firehose_replay.py --token phc_... --source-id "$(uuidgen)"
    ./firehose_replay.py --token phc_... --records 3 --events 50 --gzip-body
    ./firehose_replay.py --token phc_... --oversize      # expect 413
"""

import os
import sys
import gzip
import json
import time
import uuid
import base64
import argparse
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_URL = "http://localhost:8010/i/v1/logs/aws/firehose"
# Any ARN parses; capture-logs reads only the region in the fourth field.
DEFAULT_SOURCE_ARN = "arn:aws:firehose:us-east-1:123456789012:deliverystream/posthog-logs"
DEFAULT_LOG_GROUP = "/aws/lambda/checkout-api"

# Must exceed FIREHOSE_MAX_REQUEST_BODY_SIZE_BYTES (8 MiB) after base64, which costs 4/3.
OVERSIZE_MESSAGE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ReplayOptions:
    url: str
    token: str
    source_id: str | None
    log_group: str
    events: int
    records: int
    gzip_body: bool
    raw: bool
    oversize: bool
    control: bool
    common_attributes: str | None


class FirehoseReplay:
    """Builds one delivery and checks the response against the Firehose contract."""

    def __init__(self, options: ReplayOptions) -> None:
        self.options = options
        self.request_id = str(uuid.uuid4())

    def target_url(self) -> str:
        # Not validated here: a non-UUID source id has to reach the endpoint to be rejected.
        if self.options.source_id is None:
            return self.options.url
        return f"{self.options.url.rstrip('/')}/{self.options.source_id}"

    def cloudwatch_envelope(self, index: int, message_type: str) -> dict[str, Any]:
        now_ms = int(time.time() * 1000)
        return {
            "messageType": message_type,
            "owner": "123456789012",
            "logGroup": self.options.log_group,
            "logStream": f"2026/09/17/[$LATEST]{index:08x}",
            "subscriptionFilters": ["posthog"],
            "logEvents": [
                {
                    "id": f"{index:04d}{event:08d}",
                    "timestamp": now_ms - event,
                    "message": self.log_line(event),
                }
                for event in range(self.options.events)
            ]
            if message_type != "CONTROL_MESSAGE"
            else [],
        }

    def log_line(self, event: int) -> str:
        """Alternates the two severity paths: a JSON body, and a bare leading level token."""
        if event % 2 == 0:
            return json.dumps({"level": "warning", "msg": f"slow upstream call {event}"})
        return f"ERROR payment declined for order {event}"

    def record_payloads(self) -> list[str]:
        """One base64 of gzip per record, which is what Firehose puts in `records[].data`."""
        payloads: list[str] = []
        if self.options.control:
            # A real subscription filter opens with this, and the endpoint must skip it.
            payloads.append(self.encode(json.dumps(self.cloudwatch_envelope(0, "CONTROL_MESSAGE"))))
        for index in range(self.options.records):
            payloads.append(self.encode(self.record_body(index)))
        return payloads

    def record_body(self, index: int) -> str:
        if self.options.oversize:
            # Random so gzip cannot shrink it back under the cap.
            return base64.b64encode(os.urandom(OVERSIZE_MESSAGE_BYTES)).decode()
        if self.options.raw:
            # Not a CloudWatch envelope: VPC flow logs and WAF land on the stream like this.
            return "\n".join(f"raw line {index}.{event}" for event in range(self.options.events))
        return json.dumps(self.cloudwatch_envelope(index, "DATA_MESSAGE"))

    def encode(self, payload: str) -> str:
        return base64.b64encode(gzip.compress(payload.encode())).decode()

    def build_request(self) -> urllib.request.Request:
        body = json.dumps(
            {
                "requestId": self.request_id,
                "timestamp": int(time.time() * 1000),
                "records": [{"data": payload} for payload in self.record_payloads()],
            }
        ).encode()

        headers = {
            "Content-Type": "application/json",
            "X-Amz-Firehose-Protocol-Version": "1.0",
            "X-Amz-Firehose-Request-Id": self.request_id,
            "X-Amz-Firehose-Access-Key": self.options.token,
            "X-Amz-Firehose-Source-Arn": DEFAULT_SOURCE_ARN,
        }
        if self.options.common_attributes is not None:
            headers["X-Amz-Firehose-Common-Attributes"] = self.options.common_attributes
        if self.options.gzip_body:
            body = gzip.compress(body)
            headers["Content-Encoding"] = "gzip"

        print(f"POST {self.target_url()} ({len(body)} bytes, request id {self.request_id})")
        return urllib.request.Request(self.target_url(), data=body, headers=headers, method="POST")

    def send(self) -> tuple[int, bytes]:
        request = self.build_request()
        if request.type not in ("http", "https"):
            raise SystemExit(f"--url must be http or https, got {request.type!r}")
        try:
            # The scheme check above keeps urlopen off file:// and the other urllib schemes.
            # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            with urllib.request.urlopen(request) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            # Every status carries the contract body, so an error response is still worth checking.
            return error.code, error.read()

    def check(self, status: int, raw: bytes) -> bool:
        print(f"HTTP {status}: {raw.decode(errors='replace')}")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            print("FAIL: response is not JSON; Firehose would treat this as a 500 and retry")
            return False
        if body.get("requestId") != self.request_id:
            print(f"FAIL: requestId is {body.get('requestId')!r}, sent {self.request_id!r}")
            return False
        if "timestamp" not in body:
            print("FAIL: response has no timestamp")
            return False
        return True


def parse_args(argv: list[str] | None = None) -> ReplayOptions:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_URL, help="Endpoint without the source id.")
    parser.add_argument("--token", required=True, help="Project API key, sent as the access key.")
    parser.add_argument("--source-id", default=None, help="LogsSource id appended to the URL path.")
    parser.add_argument("--log-group", default=DEFAULT_LOG_GROUP, help="CloudWatch log group name.")
    parser.add_argument("--events", type=int, default=5, help="Log events per record.")
    parser.add_argument("--records", type=int, default=1, help="Records in the delivery.")
    parser.add_argument("--gzip-body", action="store_true", help="Also gzip the whole request body.")
    parser.add_argument("--raw", action="store_true", help="Send newline-separated lines, not an envelope.")
    parser.add_argument("--oversize", action="store_true", help="Exceed the body cap; expect 413.")
    parser.add_argument("--control", action="store_true", help="Lead with a CONTROL_MESSAGE record.")
    parser.add_argument("--common-attributes", default=None, help="JSON for the common attributes header.")
    args = parser.parse_args(argv)
    return ReplayOptions(
        url=args.url,
        token=args.token,
        source_id=args.source_id,
        log_group=args.log_group,
        events=args.events,
        records=args.records,
        gzip_body=args.gzip_body,
        raw=args.raw,
        oversize=args.oversize,
        control=args.control,
        common_attributes=args.common_attributes,
    )


def main() -> int:
    replay = FirehoseReplay(parse_args())
    status, raw = replay.send()
    return 0 if replay.check(status, raw) else 1


if __name__ == "__main__":
    sys.exit(main())
