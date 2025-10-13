"""
Snapshot constants for activity tests.
These snapshots are created in Runloop and can be used for consistent testing.
"""

from typing import TypedDict


class TestSnapshot(TypedDict):
    external_id: str
    repos: list[str]


SNAPSHOTS = [
    TestSnapshot(external_id="snp_31JAw4WPQULfJC1wPHR4H", repos=[]),
    TestSnapshot(external_id="snp_31JAwPfDgIc2DUcpqDoaH", repos=["posthog/posthog-js"]),
    TestSnapshot(external_id="snp_31JAzs4mR8AV21HwxhIHv", repos=["posthog/posthog-js", "posthog/posthog"]),
]


BASE_SNAPSHOT = SNAPSHOTS[0]
POSTHOG_JS_SNAPSHOT = SNAPSHOTS[1]
MULTI_REPO_SNAPSHOT = SNAPSHOTS[2]
