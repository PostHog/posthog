"""
Snapshot constants for activity tests.
These snapshots are created in Runloop and can be used for consistent testing.
"""

from typing import TypedDict


class TestSnapshot(TypedDict):
    external_id: str
    repos: list[str]


SNAPSHOTS = [
    TestSnapshot(external_id="snp_31KG974rmXNv2lMGVaZ8E", repos=[]),
    TestSnapshot(external_id="snp_31KG9iidgGVcyQiGmXGCd", repos=["posthog/posthog-js"]),
    TestSnapshot(external_id="snp_31KGAUUNL3Ef1ggCr3UiE", repos=["posthog/posthog-js", "posthog/posthog"]),
]


BASE_SNAPSHOT = SNAPSHOTS[0]
POSTHOG_JS_SNAPSHOT = SNAPSHOTS[1]
MULTI_REPO_SNAPSHOT = SNAPSHOTS[2]
