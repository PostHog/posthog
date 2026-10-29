from __future__ import annotations

from datetime import datetime, timedelta
from random import Random
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue

from posthog.dataclasses import frozen

BASELINE_VERSION = "2.8.0"
CURRENT_VERSION = "2.9.0"
UPLOAD_ERROR = "Upload request failed while preparing the file"
UPLOAD_FINGERPRINT = "upload-request-preparation"
DAILY_COHORT_SIZES = (85, 115, 90, 110, 125, 95, 80)


@frozen
class UploadEvent:
    event: str
    distinct_id: str
    person_id: str
    timestamp: datetime
    properties: dict[str, JsonValue]


def upload_events(anchor: datetime, *, scenario: Literal["regression", "control", "sparse"]) -> list[UploadEvent]:
    events: list[UploadEvent] = []
    days = [2] if scenario == "sparse" else range(15, 1, -1)
    for days_ago in days:
        recent = days_ago <= 8
        for browser_index, browser in enumerate(("Safari", "Chrome")):
            people_per_day = 2 if scenario == "sparse" else DAILY_COHORT_SIZES[(days_ago + browser_index) % 7]
            conversion_rate = 20 if scenario == "regression" and recent and browser == "Safari" else 80
            successful = people_per_day * conversion_rate // 100
            for index in range(people_per_day):
                identity = f"upload-cohort-{browser}-{days_ago}-{index}"
                distinct_id = str(uuid5(NAMESPACE_URL, identity))
                person_id = str(uuid5(NAMESPACE_URL, f"person-{identity}"))
                rng = Random(distinct_id)
                timestamp = anchor - timedelta(days=days_ago) + timedelta(seconds=rng.randrange(120, 23 * 3600))
                properties: dict[str, JsonValue] = {
                    "$browser": browser,
                    "$os": "Mac OS X",
                    "$current_url": "https://hedgebox.net/files/",
                    "$lib": "web",
                    "app_version": CURRENT_VERSION if recent else BASELINE_VERSION,
                    "$session_id": str(uuid5(NAMESPACE_URL, f"session-{distinct_id}")),
                }
                events.append(
                    UploadEvent(
                        event="signed_up",
                        distinct_id=distinct_id,
                        person_id=person_id,
                        timestamp=timestamp,
                        properties={**properties, "$current_url": "https://hedgebox.net/signup/", "from_invite": False},
                    )
                )
                if scenario != "sparse":
                    for event, seconds, path in (
                        ("$pageview", -90, "/"),
                        ("$pageview", -30, "/signup/"),
                        ("$identify", 5, "/signup/"),
                        ("$pageview", 15, "/files/"),
                    ):
                        events.append(
                            UploadEvent(
                                event=event,
                                distinct_id=distinct_id,
                                person_id=person_id,
                                timestamp=timestamp + timedelta(seconds=seconds),
                                properties={**properties, "$current_url": f"https://hedgebox.net{path}"},
                            )
                        )
                if index < successful and scenario != "sparse":
                    file_size = rng.randrange(1024, 8 * 1024 * 1024)
                    events.append(
                        UploadEvent(
                            event="uploaded_file",
                            distinct_id=distinct_id,
                            person_id=person_id,
                            timestamp=timestamp + timedelta(seconds=rng.randrange(60, 45 * 60)),
                            properties={
                                **properties,
                                "file_type": "image/png",
                                "file_size_b": file_size,
                                "used_mb": file_size,
                            },
                        )
                    )
                elif scenario == "regression" and recent and browser == "Safari":
                    events.append(
                        UploadEvent(
                            event="$exception",
                            distinct_id=distinct_id,
                            person_id=person_id,
                            timestamp=timestamp + timedelta(seconds=rng.randrange(60, 5 * 60)),
                            properties=properties,
                        )
                    )
    return events
