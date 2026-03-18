import re
import json
from collections.abc import Callable
from typing import Any, Literal, Optional, cast

from django.conf import settings

import dagster
import requests
import structlog

from posthog.dags.common import JobOwners
from posthog.dags.common.resources import redis
from posthog.exceptions_capture import capture_exception

logger = structlog.get_logger(__name__)

CACHE_EXPIRY = 60 * 60 * 24 * 7  # 7 days
MAX_REQUEST_RETRIES = 3
INITIAL_RETRIES_BACKOFF = 1  # in seconds


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


# Using lambda here to be able to define this before defining the functions
SDK_FETCH_FUNCTIONS: dict[SdkTypes, Callable[[], dict[str, Any]]] = {
    "web": lambda: fetch_web_sdk_data(),
    "posthog-python": lambda: fetch_python_sdk_data(),
    "posthog-node": lambda: fetch_node_sdk_data(),
    "posthog-react-native": lambda: fetch_react_native_sdk_data(),
    "posthog-flutter": lambda: fetch_flutter_sdk_data(),
    "posthog-ios": lambda: fetch_ios_sdk_data(),
    "posthog-android": lambda: fetch_android_sdk_data(),
    "posthog-go": lambda: fetch_go_sdk_data(),
    "posthog-php": lambda: fetch_php_sdk_data(),
    "posthog-ruby": lambda: fetch_ruby_sdk_data(),
    "posthog-elixir": lambda: fetch_elixir_sdk_data(),
    "posthog-dotnet": lambda: fetch_dotnet_sdk_data(),
}


def fetch_github_data_for_sdk(lib_name: str) -> Optional[dict[str, Any]]:
    """Fetch GitHub data for specific SDK type using ClickHouse $lib value."""
    fetch_fn = SDK_FETCH_FUNCTIONS.get(cast(SdkTypes, lib_name))
    if fetch_fn:
        return fetch_fn()
    return None


def fetch_sdk_data_from_releases(repo: str, tag_prefixes: list[str | re.Pattern] | None = None) -> dict[str, Any]:
    """Helper function to fetch SDK data from GitHub releases API."""

    # By default we'll include anything in the list if not specified
    if tag_prefixes is None:
        tag_prefixes = [""]

    releases = fetch_releases_from_repo(repo)
    if not releases:
        return {}

    latest_version = None
    release_dates = {}

    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue

        tag = release.get("tag_name", "")

        # Only process tags that match any of the tag prefixes
        # We also support using regex here (used to match text that starts with a number)
        version = None
        for tag_prefix in tag_prefixes:
            if isinstance(tag_prefix, re.Pattern):
                if tag_prefix.match(tag):
                    version = tag  # For regex matches we return the full tag
                    break
            else:
                if tag.startswith(tag_prefix):
                    version = tag[len(tag_prefix) :]
                    break

        if not version:
            continue

        # Latest version is always the first one we find because we go in order
        if latest_version is None:
            latest_version = version

        # Unintuitively we need to use `created_at` rather than `published_at`
        # because the former represents when the tag was created while the latter is when the release was created
        # and since some GitHub releases were backfilled we need the actual tag date
        if created_at := release.get("created_at"):
            release_dates[version] = created_at

    if not latest_version:
        return {}

    return {"latestVersion": latest_version, "releaseDates": release_dates}


# This is used to avoid hitting the GitHub API too often
# for requests coming from the same pod, this doesn't happen often but it's good to have it anyway
local_releases_cache: dict[str, list[Any]] = {}


def fetch_releases_from_repo(repo: str, skip_cache: bool = False) -> list[Any]:
    """Fetch releases from a GitHub repository"""
    global local_releases_cache

    # We don't wanna have to fight against the local cache when running tests
    # so we just skip it since the cache is only here to avoid hitting GitHub's rate limit
    # and we fully mock the requests during tests anyway
    if settings.TEST:
        skip_cache = True

    if repo in local_releases_cache and not skip_cache:
        logger.info(f"[SDK Doctor] Returning cached releases for {repo}")
        return local_releases_cache[repo]

    releases = []
    page = 1

    while page <= 10:  # Github only permits us to list the first 1000 items, so that's 100 items * 10 pages
        try:
            url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"
            logger.info(f"[SDK Doctor] Fetching releases from {url}")

            response = requests.get(url, timeout=10)

            if not response.ok:
                logger.error(f"[SDK Doctor] Failed to fetch releases for {repo}", status_code=response.status_code)
                break

            releases_json = response.json()
            if releases_json is None:
                logger.error(f"[SDK Doctor] Expected list of releases, got empty response", repo=repo)
                break

            if not isinstance(releases_json, list):
                logger.error(f"[SDK Doctor] Expected list of releases, got {type(releases_json)}", repo=repo)
                break

            if len(releases_json) == 0:
                break

            releases.extend(releases_json)
            page += 1
        except Exception as e:
            logger.exception(f"[SDK Doctor] Failed to fetch releases for {repo}", repo=repo)
            capture_exception(e, additional_properties={"repo": repo, "page": page, "url": url})
            break

    # Cache for later use and return
    local_releases_cache[repo] = releases
    return local_releases_cache[repo]


def fetch_web_sdk_data() -> dict[str, Any]:
    """Fetch Web SDK data from GitHub releases API"""

    # Newer versions in `posthog-js` use a monorepo approach where we prefix tags with `posthog-js@`
    # while older versions before the monorepo used simple `v`-prefixed tags
    return fetch_sdk_data_from_releases("PostHog/posthog-js", tag_prefixes=["posthog-js@", "v"])


def fetch_python_sdk_data() -> dict[str, Any]:
    """Fetch Python SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-python", tag_prefixes=["v"])


def fetch_node_sdk_data() -> dict[str, Any]:
    """Fetch Node.js SDK data from GitHub releases API"""

    # `posthog-node` was originally developed on the `posthog-js-lite` repo, but was later moved to the `posthog-js` monorepo
    # We fetch the latest version from both repos and join them together.
    posthog_js = fetch_sdk_data_from_releases("PostHog/posthog-js", tag_prefixes=["posthog-node@"])
    posthog_js_lite = fetch_sdk_data_from_releases("PostHog/posthog-js-lite", tag_prefixes=["posthog-node-v"])

    # Shouldn't happen, but just in case
    if not posthog_js:
        return {}

    # The latest date is always from `posthog-js` since this is the only active repo
    return {
        "latestVersion": posthog_js["latestVersion"],
        "releaseDates": {
            **posthog_js["releaseDates"],
            **posthog_js_lite.get("releaseDates", {}),
        },
    }


def fetch_react_native_sdk_data() -> dict[str, Any]:
    """Fetch React Native SDK data from GitHub releases API"""

    # `posthog-react-native` was originally developed on the `posthog-js-lite` repo, but was later moved to the `posthog-js` monorepo
    # We fetch the latest version from both repos and join them together.
    posthog_js = fetch_sdk_data_from_releases("PostHog/posthog-js", tag_prefixes=["posthog-react-native@"])
    posthog_js_lite = fetch_sdk_data_from_releases("PostHog/posthog-js-lite", tag_prefixes=["posthog-react-native-v"])

    # Shouldn't happen, but just in case
    if not posthog_js:
        return {}

    # The latest date is always from `posthog-js` since this is the only active repo
    return {
        "latestVersion": posthog_js["latestVersion"],
        "releaseDates": {
            **posthog_js["releaseDates"],
            **posthog_js_lite.get("releaseDates", {}),
        },
    }


def fetch_flutter_sdk_data() -> dict[str, Any]:
    """Fetch Flutter SDK data from GitHub releases API"""
    # First attempt to cut the trailing `v` prefix and then just fallback to the full tag
    return fetch_sdk_data_from_releases("PostHog/posthog-flutter", tag_prefixes=["v", ""])


def fetch_ios_sdk_data() -> dict[str, Any]:
    """Fetch iOS SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-ios")


def fetch_android_sdk_data() -> dict[str, Any]:
    """Fetch Android SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-android", tag_prefixes=["android-v", re.compile(r"[0-9]")])


def fetch_go_sdk_data() -> dict[str, Any]:
    """Fetch Go SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-go", tag_prefixes=["v"])


def fetch_php_sdk_data() -> dict[str, Any]:
    """Fetch PHP SDK data from History.md with release dates"""
    return fetch_sdk_data_from_releases("PostHog/posthog-php")


def fetch_ruby_sdk_data() -> dict[str, Any]:
    """Fetch Ruby SDK data from CHANGELOG.md with release dates"""
    return fetch_sdk_data_from_releases("PostHog/posthog-ruby")


def fetch_elixir_sdk_data() -> dict[str, Any]:
    """Fetch Elixir SDK data from CHANGELOG.md with release dates"""
    return fetch_sdk_data_from_releases("PostHog/posthog-elixir", tag_prefixes=["v"])


def fetch_dotnet_sdk_data() -> dict[str, Any]:
    """Fetch .NET SDK data from GitHub releases API"""
    return fetch_sdk_data_from_releases("PostHog/posthog-dotnet", tag_prefixes=["v"])


# ---- Dagster defs
retry_policy = dagster.RetryPolicy(
    max_retries=3,
    delay=1,
    backoff=dagster.Backoff.EXPONENTIAL,
    jitter=dagster.Jitter.FULL,
)


@dagster.op(retry_policy=retry_policy)
def fetch_github_sdk_versions_op(context: dagster.OpExecutionContext) -> dict[str, Optional[dict[str, Any]]]:
    """Fetch GitHub SDK version data for all SDK types."""
    sdk_data = {}
    fetched_count = 0
    failed_count = 0

    for lib_name in SDK_TYPES:
        try:
            context.log.info(f"Fetching {lib_name} SDK data from GitHub")
            github_data = fetch_github_data_for_sdk(lib_name)

            if github_data:
                sdk_data[lib_name] = github_data
                fetched_count += 1
                context.log.info(f"Successfully fetched {lib_name} SDK data")
            else:
                failed_count += 1
                context.log.warning(f"No data received from GitHub for {lib_name}")
        except Exception as e:
            failed_count += 1
            context.log.exception(f"Failed to fetch {lib_name} SDK data")
            capture_exception(e)

    context.log.info(f"Fetched {fetched_count} SDK versions")
    context.log.info(f"Failed to fetch {failed_count} SDK versions")
    context.log.info(f"Total SDKs: {len(SDK_TYPES)}")
    context.log.info(f"SDK data: {sdk_data}")

    context.add_output_metadata(
        {
            "fetched_count": dagster.MetadataValue.int(fetched_count),
            "failed_count": dagster.MetadataValue.int(failed_count),
            "total_sdks": dagster.MetadataValue.int(len(SDK_TYPES)),
        }
    )

    return sdk_data  # type: ignore


@dagster.op(retry_policy=retry_policy)
def cache_github_sdk_versions_op(
    context: dagster.OpExecutionContext,
    sdk_data: dict[str, Optional[dict[str, Any]]],
    redis_client: dagster.ResourceParam[redis.Redis],
) -> None:
    """Cache GitHub SDK version data to Redis."""
    cached_count = 0
    skipped_count = 0

    for lib_name, github_data in sdk_data.items():
        if github_data is None:
            skipped_count += 1
            continue

        cache_key = f"github:sdk_versions:{lib_name}"
        try:
            redis_client.setex(cache_key, CACHE_EXPIRY, json.dumps(github_data))
            cached_count += 1
            context.log.info(f"Successfully cached {lib_name} SDK data")
        except Exception as e:
            context.log.exception(f"Failed to cache {lib_name} SDK data")
            capture_exception(e)

    context.log.info(f"Cached {cached_count} SDK versions")
    context.log.info(f"Skipped {skipped_count} SDK versions")
    context.log.info(f"Total SDKs: {len(sdk_data)}")
    context.log.info(f"SDK data: {sdk_data}")

    context.add_output_metadata(
        {
            "cached_count": dagster.MetadataValue.int(cached_count),
            "skipped_count": dagster.MetadataValue.int(skipped_count),
            "total_sdks": dagster.MetadataValue.int(len(sdk_data)),
        }
    )


@dagster.job(
    description="Queries GitHub for most recent SDK versions and caches them in Redis",
    tags={"owner": JobOwners.TEAM_GROWTH.value},
)
def cache_github_sdk_versions_job():
    sdk_data = fetch_github_sdk_versions_op()
    cache_github_sdk_versions_op(sdk_data)


cache_github_sdk_versions_schedule = dagster.ScheduleDefinition(
    job=cache_github_sdk_versions_job,
    cron_schedule="30 * * * *",  # Every hour at half past the hour
    execution_timezone="UTC",
    name="cache_github_sdk_versions_schedule",
)
