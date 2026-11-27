"""Batch audience sizing: the preview counts the editor shows, and the account audience pages the Node
batch resolver walks when it sends."""

import json
import hashlib
from collections.abc import Callable
from time import monotonic, sleep
from typing import Any, TypeVar
from uuid import uuid4

from django.core.cache import caches

import structlog

from posthog.models.property import GroupTypeIndex
from posthog.models.team.team import Team

from products.feature_flags.backend.user_blast_radius import BlastRadiusResult, get_user_blast_radius
from products.workflows.backend.facade.contracts import AudiencePage, AudienceSize, RealtimeAudienceCohort
from products.workflows.backend.services.account_audience import (
    ACCOUNT_BATCH_SIZE,
    get_account_audience_count,
    get_account_audience_page,
    get_account_group_type_name as _get_account_group_type_name,
)
from products.workflows.backend.services.audience_v2 import (
    count_person_total,
    get_dedupe_audience_count_v2,
    get_person_audience_count_v2,
)
from products.workflows.backend.services.batch_audience_cohorts import (
    find_realtime_behavioral_cohort,
    realtime_audience_cohort,
    realtime_cohort_can_finish,
    realtime_cohort_is_ready,
    realtime_cohort_status,
)
from products.workflows.backend.services.batch_audience_test_accounts import skipped_test_account_filter_keys
from products.workflows.backend.utils.batch_trigger_limit import resolve_batch_audience_limit

logger = structlog.get_logger(__name__)
counts_cache = caches["workflows_audience_counts"]

# The editor re-sizes the audience on every open and every filter edit, so the same audience is counted again and
# again within minutes, and each count reads the team's whole person table. The preview is a sampled estimate, so a
# few minutes of staleness doesn't change what it tells the user. The person total is cached on its own.
AUDIENCE_COUNT_CACHE_SECONDS = 600
COUNTING_LOCK_SECONDS = 200
# Below the 120s ingress timeout, so a waiter whose leader died still answers before the client gives up.
COUNTING_WAIT_SECONDS = 60
COUNTING_POLL_SECONDS = 0.5

T = TypeVar("T")


def _shared_count(cache_key: str, count: Callable[[], T], *, refresh: bool, wait_until: float) -> T:
    """Reuse a recent count, wait until `wait_until` for the same count already in flight, or count and store it for
    the next caller. `refresh` always counts again, and its result still replaces the stored one."""
    lock_key = f"{cache_key}:counting"
    lock_token: str | None = None
    if not refresh:
        while True:
            cached = counts_cache.get(cache_key)
            if cached is not None:
                return cached
            token = str(uuid4())
            if counts_cache.add(lock_key, token, COUNTING_LOCK_SECONDS):
                lock_token = token
                # The previous holder can store its result and release between the read above and this add.
                cached = counts_cache.get(cache_key)
                if cached is not None:
                    counts_cache.delete(lock_key)
                    return cached
                break
            if monotonic() >= wait_until:
                break
            sleep(COUNTING_POLL_SECONDS)
    try:
        result = count()
        try:
            counts_cache.set(cache_key, result, AUDIENCE_COUNT_CACHE_SECONDS)
        except Exception:
            logger.warning("workflows_audience_count_cache_write_failed", cache_key=cache_key, exc_info=True)
        return result
    finally:
        if lock_token is not None and counts_cache.get(lock_key) == lock_token:
            counts_cache.delete(lock_key)


def _person_total(team: Team, *, refresh: bool, wait_until: float) -> int:
    return _shared_count(
        f"workflows:audience_person_total:{team.pk}",
        lambda: count_person_total(team),
        refresh=refresh,
        wait_until=wait_until,
    )


def _count_audience(
    team: Team,
    filters: dict,
    group_type_index: GroupTypeIndex | None,
    dedupe_key: str | None,
    *,
    refresh: bool,
    wait_until: float,
) -> BlastRadiusResult:
    if group_type_index is not None:
        return get_user_blast_radius(team, filters, group_type_index)
    total = _person_total(team, refresh=refresh, wait_until=wait_until)
    if dedupe_key is not None:
        return get_dedupe_audience_count_v2(team, filters, dedupe_key, total=total)
    return get_person_audience_count_v2(team, filters, total=total)


def _cached_count_audience(
    team: Team, filters: dict, group_type_index: GroupTypeIndex | None, dedupe_key: str | None, *, refresh: bool
) -> BlastRadiusResult:
    audience = json.dumps(
        [filters, group_type_index, dedupe_key, team.test_account_filters], sort_keys=True, default=str
    )
    # One deadline for the audience lock and the person-total lock inside it, so a request never waits on both in turn.
    wait_until = monotonic() + COUNTING_WAIT_SECONDS
    return _shared_count(
        f"workflows:audience_count:v2:{team.pk}:{hashlib.sha256(audience.encode()).hexdigest()}",
        lambda: _count_audience(team, filters, group_type_index, dedupe_key, refresh=refresh, wait_until=wait_until),
        refresh=refresh,
        wait_until=wait_until,
    )


def _top_level_cohort_ids(filters: dict) -> list[int | str]:
    """Cohort ids of the audience's top-level conditions, the only ones the pickers can show and clear."""
    properties = filters.get("properties")
    if not isinstance(properties, list):
        return []
    return [
        condition["value"]
        for condition in properties
        if isinstance(condition, dict)
        and condition.get("type") == "cohort"
        and isinstance(condition.get("value"), int | str)
    ]


def get_audience_size(
    *,
    team_id: int,
    filters: dict,
    group_type_index: GroupTypeIndex | None,
    dedupe_key: str | None,
    sends_email: bool,
    email_rate_limit: dict[str, Any] | None = None,
    refresh: bool = True,
) -> AudienceSize:
    team = Team.objects.get(id=team_id)
    audience_limit = resolve_batch_audience_limit(team_id, sends_email=sends_email, email_rate_limit=email_rate_limit)
    # Preview matches the actual send: with dedup active, "affected" is the number of
    # sends (unique emails + email-less persons), not the number of matching persons.
    # The applied key is echoed back so the frontend labels the count from the response
    # instead of guessing whether the dedup actually ran.
    applied_dedupe_key = None
    realtime_cohort = realtime_audience_cohort(team.project_id, filters) if group_type_index is None else None
    if realtime_cohort is not None:
        # The send reads the realtime pipeline's Postgres table, which this process can't query. The
        # cohort's count from its periodic calculation stands in as an estimate, and the send skips the
        # email dedupe.
        return AudienceSize(
            affected=realtime_cohort.count or 0,
            # A send screen re-sizes a calculating realtime cohort every few seconds, so even a refresh reuses the total.
            total=_person_total(team, refresh=False, wait_until=monotonic() + COUNTING_WAIT_SECONDS),
            limit=audience_limit.limit,
            dedupe_key=None,
            realtime_cohort=realtime_cohort_status(realtime_cohort),
            rate_limited=audience_limit.rate_limited,
        )
    if group_type_index is None:
        applied_dedupe_key = dedupe_key
    blast_radius = _cached_count_audience(team, filters, group_type_index, applied_dedupe_key, refresh=refresh)

    mixed_realtime_cohort = (
        find_realtime_behavioral_cohort(team.project_id, _top_level_cohort_ids(filters))
        if group_type_index is None
        else None
    )
    return AudienceSize(
        affected=blast_radius.affected,
        total=blast_radius.total,
        limit=audience_limit.limit,
        dedupe_key=applied_dedupe_key,
        rate_limited=audience_limit.rate_limited,
        skipped_test_account_filters=(
            skipped_test_account_filter_keys(team, filters) if group_type_index is None else []
        ),
        realtime_cohort_with_other_conditions=(
            RealtimeAudienceCohort(
                id=mixed_realtime_cohort.pk,
                name=str(mixed_realtime_cohort.name),
                ready=realtime_cohort_is_ready(mixed_realtime_cohort),
                can_finish=realtime_cohort_can_finish(mixed_realtime_cohort),
            )
            if mixed_realtime_cohort is not None
            else None
        ),
    )


def get_account_audience_size(
    *, team_id: int, filters: dict, sends_email: bool, email_rate_limit: dict[str, Any] | None = None
) -> AudienceSize:
    team = Team.objects.get(id=team_id)
    audience_limit = resolve_batch_audience_limit(team_id, sends_email=sends_email, email_rate_limit=email_rate_limit)
    return AudienceSize(
        affected=get_account_audience_count(team, filters),
        total=get_account_audience_count(team, {"audience_type": "accounts"}),
        limit=audience_limit.limit,
        dedupe_key=None,
        rate_limited=audience_limit.rate_limited,
    )


def get_account_audience_ids_page(*, team_id: int, filters: dict, cursor: str | None) -> AudiencePage:
    ids = get_account_audience_page(Team.objects.get(id=team_id), filters, cursor)
    return AudiencePage(ids=ids, has_more=len(ids) == ACCOUNT_BATCH_SIZE)


def get_account_group_type_name(team_id: int) -> str | None:
    return _get_account_group_type_name(Team.objects.get(id=team_id))
