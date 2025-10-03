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
    TestSnapshot(external_id="snp_31DQ1OhCtOXiMaR4UAYXx", repos=[]),
    TestSnapshot(external_id="snp_31DQ2BxMGkbMnXeedSf4H", repos=["PostHog/posthog-js"]),
    TestSnapshot(external_id="snp_31DQ6FMEcNQLJqlGWYabH", repos=["PostHog/posthog-js", "PostHog/posthog"]),
]

# Quick access to specific snapshots
BASE_SNAPSHOT = SNAPSHOTS[0]
POSTHOG_JS_SNAPSHOT = SNAPSHOTS[1]
MULTI_REPO_SNAPSHOT = SNAPSHOTS[2]
