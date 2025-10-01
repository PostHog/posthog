"""
Snapshot constants for activity tests.
These snapshots are created in Runloop and can be used for consistent testing.
"""

from typing import TypedDict


class TestSnapshot(TypedDict):
    external_id: str
    repos: list[str]


# Available test snapshots
SNAPSHOTS = [
    TestSnapshot(external_id="snp_31CK3NN6HOMsIcZCdjR3V", repos=[]),
    TestSnapshot(external_id="snp_31CK478qWpVFVzA47Porh", repos=["PostHog/posthog-js"]),
]

# Quick access to specific snapshots
BASE_SNAPSHOT = SNAPSHOTS[0]
POSTHOG_JS_SNAPSHOT = SNAPSHOTS[1]
