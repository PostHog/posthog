from typing import Literal, TypedDict

SDK_CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days — used by the GitHub `latestVersion` cache (hourly Dagster job)

# Team-events snapshot TTL — sized to self-heal one missed daily cron run.
# The Temporal `sdk_outdated` cron starts at 08:00 UTC; per-team writes happen mid-batch, so the
# previous day's write for any given team can be timestamped meaningfully later. A 26h TTL gives
# ~2h headroom relative to cron *start*, and less for teams late in the batch queue. That's
# deliberate: when a team's TTL expires before its next batch slot, the next user request hits
# the cache-miss fallback in posthog/api/sdk_health.py:get_team_data, which runs one fresh
# single-team HogQL query and repopulates Redis. Steady-state load is unchanged; the trade-off
# prevents days-long stale snapshots when a team's batch is skipped or times out.
TEAM_SDK_CACHE_EXPIRY = 60 * 60 * 26  # 26 hours


# Canonical list of the SDK identifiers SDK Health tracks. Lives here (rather than in
# products/growth/dags/github_sdk_versions.py) so non-Dagster consumers — the Temporal
# health check, the API view, and tests — don't need to import from a Dagster module.
SdkTypes = Literal[
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-dotnet",
    "posthog-elixir",
]
SDK_TYPES: list[SdkTypes] = [
    "web",
    "posthog-ios",
    "posthog-android",
    "posthog-node",
    "posthog-python",
    "posthog-php",
    "posthog-ruby",
    "posthog-go",
    "posthog-flutter",
    "posthog-react-native",
    "posthog-dotnet",
    "posthog-elixir",
]


class SdkVersionEntry(TypedDict):
    lib_version: str
    max_timestamp: str
    count: int


# Identity matching ClickHouse tables, written by products/growth/dags/identity_matching.py.
# Live here so the API view doesn't need to import from a Dagster module.
IDENTITY_MATCHING_DEVICE_DAYS_TABLE = "identity_matching_device_days"
IDENTITY_MATCHING_PERSON_TIMELINE_TABLE = "identity_matching_person_timeline"
IDENTITY_MATCHING_CANDIDATE_PAIRS_TABLE = "identity_matching_candidate_pairs"
IDENTITY_MATCHING_LINKS_TABLE = "identity_matching_links"

IDENTITY_MATCHING_RULES_MODEL_VERSION = "rules_v1"
IDENTITY_MATCHING_LOGREG_MODEL_VERSION = "logreg_v1"
IDENTITY_MATCHING_TIERS = ["high", "medium", "low"]


def github_sdk_versions_key(sdk_type: str) -> str:
    return f"github:sdk_versions:{sdk_type}"


def team_sdk_versions_key(team_id: int) -> str:
    return f"sdk_versions:team:{team_id}"
