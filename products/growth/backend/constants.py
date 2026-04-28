from typing import Literal, TypedDict

SDK_CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days


# Canonical list of the SDK identifiers SDK Doctor tracks. Lives here (rather than in
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


def github_sdk_versions_key(sdk_type: str) -> str:
    return f"github:sdk_versions:{sdk_type}"


def team_sdk_versions_key(team_id: int) -> str:
    return f"sdk_versions:team:{team_id}"
