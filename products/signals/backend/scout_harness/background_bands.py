"""Nightly activity bands for the background scout lane.

The coordinator samples a percentage of each band from the `background.bands` block of the
`signals-scout` flag payload (see `team_limits._parse_background`). This module decides which
projects are eligible and which band each one is in, once a day, so the 30-minute coordinator tick
reads one small table instead of ClickHouse.

A project is eligible only when all of these hold:

- it did not set Signals up (`suggestions.set_up_team_q`)
- its organization approved AI data processing
- it is a root project, not a demo, and its organization is not the internal-metrics one
- it is the project where the most recently active member of its organization last worked

Bands, first match wins. "Paying" is `Organization.has_active_subscription is True`, so an
organization that billing never synced counts as not paying.

| Band | Rule |
|---|---|
| 1 | paying, 5,000 or more events a day, a member logged in within 14 days |
| 2 | paying, 500 to 5,000 events a day, a member logged in within 14 days |
| 3 | not paying, 500 or more events a day, a member logged in within 14 days |
| 4 | 500 or more events a day, last member login 15 to 30 days ago |
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Iterator
from datetime import datetime, timedelta
from itertools import batched

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.models.event.new_events_schema import events_read_table, use_new_events_schema

from products.signals.backend.models import SignalScoutBackgroundBand
from products.signals.backend.scout_harness.suggestions import set_up_team_q

HIGH_VOLUME_EVENTS_PER_DAY = 5_000
MIN_EVENTS_PER_DAY = 500
RECENT_LOGIN_DAYS = 14
MAX_LOGIN_DAYS = 30
# A week evens out the weekday and weekend traffic of one project.
EVENT_WINDOW_DAYS = 7
# `sync_execute` sets no wall-clock cap, so a stalled read would otherwise hold a Celery worker.
EVENT_READ_MAX_EXECUTION_S = 600
# Keeps each `IN (...)` list far below the Postgres bind-parameter limit.
ID_BATCH_SIZE = 5_000


@frozen
class BandOutcome:
    written: int
    removed: int


@frozen
class _OrgActivity:
    team_id: int
    last_login: datetime


def _id_batches(ids: Collection[int]) -> Iterator[tuple[int, ...]]:
    return batched(sorted(ids), ID_BATCH_SIZE, strict=False)


def _root_team_id(team_id: int, parent_team_id: int | None) -> int:
    return parent_team_id or team_id


def _most_active_project_by_org(login_cutoff: datetime) -> dict[int, _OrgActivity]:
    """Per organization: the root project of the member who logged in last, and when that was.

    `current_team` is the project that member last had open. A child environment counts as its
    parent project, because background configs live on the root project.
    """
    rows = (
        User.objects.filter(is_active=True, last_login__gte=login_cutoff, current_team__isnull=False)
        .order_by("-last_login")
        .values_list("current_team_id", "current_team__parent_team_id", "current_team__organization_id", "last_login")
    )
    by_org: dict[int, _OrgActivity] = {}
    for team_id, parent_team_id, organization_id, last_login in rows.iterator():
        if organization_id not in by_org:
            by_org[organization_id] = _OrgActivity(
                team_id=_root_team_id(team_id, parent_team_id), last_login=last_login
            )
    return by_org


def _eligible_teams(team_ids: set[int]) -> dict[int, bool]:
    """`team_id -> paying` for each project in `team_ids` that can get a background scout."""
    eligible: dict[int, bool] = {}
    for batch in _id_batches(team_ids):
        rows = (
            Team.objects.filter(
                Q(parent_team_id__isnull=True) | Q(parent_team_id=F("id")),
                id__in=batch,
                is_demo=False,
                organization__is_ai_data_processing_approved=True,
                organization__for_internal_metrics=False,
            )
            .exclude(set_up_team_q())
            .values_list("id", "organization__has_active_subscription")
        )
        eligible.update((team_id, paying is True) for team_id, paying in rows)
    return eligible


def _events_per_day_by_org(organization_ids: Collection[int], begin: datetime, end: datetime) -> dict[int, float]:
    """Average daily events of each organization in `organization_ids` over `[begin, end)`, from one fleet-wide query.

    Organization-level volume is enough to band a project, and it counts child environments too.
    """
    tag_queries(product=Product.SIGNALS, query_type="SignalsScoutBackgroundBands")
    rows = sync_execute(  # nosemgrep: clickhouse-fstring-param-audit - the table is events_read_table() output; every value is parameterized
        f"""
        SELECT team_id, count() AS events
        FROM {events_read_table(use_new_events_schema())}
        WHERE timestamp >= %(begin)s AND timestamp < %(end)s
        GROUP BY team_id
        """,
        {"begin": begin, "end": end},
        workload=Workload.OFFLINE,
        settings={"max_execution_time": EVENT_READ_MAX_EXECUTION_S},
    )
    events_by_team = dict(rows)
    days = (end - begin).total_seconds() / 86_400
    by_org: dict[int, float] = defaultdict(float)
    for batch in _id_batches(organization_ids):
        for team_id, organization_id in Team.objects.filter(organization_id__in=batch).values_list(
            "id", "organization_id"
        ):
            by_org[organization_id] += events_by_team.get(team_id, 0) / days
    return by_org


def band_for(*, paying: bool, events_per_day: float, last_login: datetime, now: datetime) -> int | None:
    if events_per_day < MIN_EVENTS_PER_DAY or last_login < now - timedelta(days=MAX_LOGIN_DAYS):
        return None
    if last_login < now - timedelta(days=RECENT_LOGIN_DAYS):
        return 4
    if not paying:
        return 3
    return 1 if events_per_day >= HIGH_VOLUME_EVENTS_PER_DAY else 2


def compute_background_bands(now: datetime | None = None) -> dict[int, int]:
    """`team_id -> band` for every eligible project."""
    now = now or timezone.now()
    activity_by_org = _most_active_project_by_org(now - timedelta(days=MAX_LOGIN_DAYS))
    eligible = _eligible_teams({activity.team_id for activity in activity_by_org.values()})
    # The org's most active project must itself be eligible. The org never falls back to a
    # quieter project, so a set-up org does not get a background scout next to its own setup.
    activity_by_org = {
        organization_id: activity
        for organization_id, activity in activity_by_org.items()
        if activity.team_id in eligible
    }
    if not activity_by_org:
        return {}
    day_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events_by_org = _events_per_day_by_org(activity_by_org.keys(), day_end - timedelta(days=EVENT_WINDOW_DAYS), day_end)
    bands: dict[int, int] = {}
    for organization_id, activity in activity_by_org.items():
        band = band_for(
            paying=eligible[activity.team_id],
            events_per_day=events_by_org.get(organization_id, 0.0),
            last_login=activity.last_login,
            now=now,
        )
        if band is not None:
            bands[activity.team_id] = band
    return bands


def refresh_background_bands(now: datetime | None = None) -> BandOutcome:
    """Recompute the bands and replace the table. A project that stopped being eligible loses its row."""
    now = now or timezone.now()
    bands = compute_background_bands(now)
    departed = set(SignalScoutBackgroundBand.all_teams.values_list("team_id", flat=True)) - bands.keys()
    with transaction.atomic():
        removed = 0
        for batch in _id_batches(departed):
            deleted, _ = SignalScoutBackgroundBand.all_teams.filter(team_id__in=batch).delete()
            removed += deleted
        SignalScoutBackgroundBand.all_teams.bulk_create(
            [SignalScoutBackgroundBand(team_id=team_id, band=band, computed_at=now) for team_id, band in bands.items()],
            update_conflicts=True,
            unique_fields=["team"],
            update_fields=["band", "computed_at"],
            batch_size=1000,
        )
    return BandOutcome(written=len(bands), removed=removed)
