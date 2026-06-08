from collections import defaultdict
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

import structlog
from structlog.stdlib import BoundLogger

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models import Team
from posthog.tasks.usage_report import get_ph_client

from products.growth.backend.constants import SDK_TYPES

default_logger: BoundLogger = structlog.get_logger(__name__)

# Group properties written by the snapshot. `sdk_version_keys_current` is the queryable surface
# Sales/CS use to find every org/customer currently on a given SDK version (e.g. "posthog-php@3.4.0").
SDK_VERSION_KEYS_PROPERTY = "sdk_version_keys_current"
SDK_LIBS_PROPERTY = "sdk_libs_current"
SDK_VERSIONS_UPDATED_AT_PROPERTY = "sdk_versions_updated_at"

# Match the SDK Doctor lookback so "current" means the same thing across the product.
LOOKBACK_DAYS = 7

# All-teams aggregation grouped by team — mirrors the full-scan grouped queries usage_report runs.
# Uses materialized columns (no property-map lookup) and pre-filters to tracked SDKs to bound
# cardinality. We only need presence of each lib@version per team, so no counts/timestamps.
# Scanned one day at a time (see _fetch_team_sdk_keys) so a 7-day lookback never reads the whole
# window in a single pass.
SDK_VERSIONS_BY_TEAM_SQL = """
SELECT
    team_id,
    `mat_$lib` AS lib,
    `mat_$lib_version` AS lib_version
FROM events
WHERE
    timestamp >= %(begin)s AND timestamp < %(end)s
    AND `mat_$lib` IN %(sdk_types)s
    AND `mat_$lib_version` IS NOT NULL
    AND `mat_$lib_version` != ''
GROUP BY team_id, lib, lib_version
"""


def _fetch_team_sdk_keys(*, lookback_days: int = LOOKBACK_DAYS) -> dict[int, set[str]]:
    """Return, per team, the set of `{lib}@{lib_version}` keys seen in the lookback window.

    The lookback is split into single-day scans whose per-team presence is unioned — the result is
    identical to one wide scan, but each query stays small (mirrors the time-splitting usage_report
    uses for its heavy event scans). Runs on the OFFLINE cluster's default settings.
    """
    team_keys: defaultdict[int, set[str]] = defaultdict(set)
    now = timezone.now()
    with tags_context(product=Product.SDK_DOCTOR, feature=Feature.USAGE_REPORT):
        for day in range(lookback_days):
            end = now - timedelta(days=day)
            begin = end - timedelta(days=1)
            rows = sync_execute(
                SDK_VERSIONS_BY_TEAM_SQL,
                {"begin": begin, "end": end, "sdk_types": SDK_TYPES},
                workload=Workload.OFFLINE,
            )
            for team_id, lib, lib_version in rows:
                team_keys[team_id].add(f"{lib}@{lib_version}")
    return team_keys


def _roll_up_to_groups(
    team_keys: dict[int, set[str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Roll team-level SDK keys up to organization and customer group keys.

    Returns (org_key -> keys, customer_key -> keys). A team contributes to its organization
    group (keyed by org UUID) and, when the org has a billing customer_id, to that customer
    group (keyed by customer_id) — unioning across every org that shares the customer_id.
    """
    if not team_keys:
        return {}, {}

    teams = (
        Team.objects.select_related("organization")
        .exclude(Q(organization__for_internal_metrics=True) | Q(is_demo=True))
        .only("id", "organization__id", "organization__customer_id")
    )

    org_keys: defaultdict[str, set[str]] = defaultdict(set)
    customer_keys: defaultdict[str, set[str]] = defaultdict(set)
    for team in teams:
        keys = team_keys.get(team.id)
        if not keys:
            continue
        org_keys[str(team.organization.id)] |= keys
        customer_id = team.organization.customer_id
        if customer_id:
            customer_keys[customer_id] |= keys

    return dict(org_keys), dict(customer_keys)


def _group_properties(keys: set[str], updated_at: str) -> dict[str, object]:
    return {
        SDK_VERSION_KEYS_PROPERTY: sorted(keys),
        SDK_LIBS_PROPERTY: sorted({key.split("@", 1)[0] for key in keys}),
        SDK_VERSIONS_UPDATED_AT_PROPERTY: updated_at,
    }


def snapshot_sdk_versions_to_groups(
    *,
    lookback_days: int = LOOKBACK_DAYS,
    logger: BoundLogger = default_logger,
) -> dict[str, int]:
    """Snapshot each org's and customer's current SDK versions onto PostHog group properties.

    PostHog-first v1: lets Sales/CS self-serve "which managed customers are on SDK X version Y"
    by filtering the organization/customer groups on `sdk_version_keys_current`.
    """
    team_keys = _fetch_team_sdk_keys(lookback_days=lookback_days)
    org_keys, customer_keys = _roll_up_to_groups(team_keys)

    pha_client = get_ph_client(sync_mode=True)
    updated_at = timezone.now().isoformat()
    written = {"organizations": 0, "customers": 0}

    for group_type, group_data, counter in (
        ("organization", org_keys, "organizations"),
        ("customer", customer_keys, "customers"),
    ):
        for group_key, keys in group_data.items():
            try:
                pha_client.group_identify(
                    group_type=group_type,
                    group_key=group_key,
                    properties=_group_properties(keys, updated_at),
                )
                written[counter] += 1
            except Exception as err:
                logger.exception(f"[SDK version snapshot] Failed to update {group_type} group {group_key}: {err}")
                capture_exception(err, {"group_type": group_type, "group_key": group_key})

    logger.info(
        "[SDK version snapshot] Updated group properties",
        organizations=written["organizations"],
        customers=written["customers"],
    )
    return written
