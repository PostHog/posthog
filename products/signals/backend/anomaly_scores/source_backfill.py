"""Turn on the Product analytics source for self-driving projects that completed setup before onboarding enabled it.

Scoring enrolls a team only through an enabled `analytics / anomaly_investigation` row, and onboarding is the only
path that writes one for a self-driving project. The backfill writes the row with `alert_scope: off`, so no firing
alert or investigation becomes a signal. Each written row carries a marker, so a revert removes only those rows.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet

import structlog

from posthog.models import Team

from products.signals.backend.anomaly_scores.config import enrolls_team, read_config, read_payload
from products.signals.backend.contracts import ALERT_SCOPE_KEY, ALERT_SCOPE_SOURCE, AlertScope
from products.signals.backend.models import SignalSourceConfig, SignalTeamConfig

logger = structlog.get_logger(__name__)

BACKFILL_MARKER_KEY = "backfilled_by"
BACKFILL_MARKER = "enable_analytics_source_for_self_driving"
BACKFILL_CONFIG: dict[str, str] = {ALERT_SCOPE_KEY: AlertScope.OFF.value, BACKFILL_MARKER_KEY: BACKFILL_MARKER}


@dataclass(frozen=False)
class BackfillSummary:
    matched: int = 0
    # Matched teams that the scoring flag payload enrolls now, so the row starts scoring them on the next tick.
    in_rollout: int = 0
    created: int = 0
    # A row for the team appeared between the batch read and the write.
    not_created: int = 0
    team_ids: list[int] = field(default_factory=list)


@dataclass(frozen=False)
class RevertSummary:
    matched: int = 0
    # A person or onboarding changed the row after the backfill wrote it, so the revert keeps it.
    skipped_changed: int = 0
    deleted: int = 0
    team_ids: list[int] = field(default_factory=list)


def _source_rows(team_ids: list[int] | None = None) -> QuerySet[SignalSourceConfig]:
    source_product, source_type = ALERT_SCOPE_SOURCE
    rows = SignalSourceConfig.objects.filter(source_product=source_product, source_type=source_type)
    return rows.filter(team_id__in=team_ids) if team_ids is not None else rows


def self_driving_team_ids_without_source(
    *, team_ids: list[int] | None, after_team_id: int | None, limit: int
) -> list[int]:
    """Teams that completed self-driving setup, have no analytics source row, and did not turn scoring off.

    A disabled row counts as a row: a person turned the source off, and the backfill must not turn it on again.
    """
    configs = (
        SignalTeamConfig.objects.filter(onboarding__completed_at__isnull=False)
        .exclude(onboarding__completed_at=None)
        .exclude(anomaly_scoring_enabled=False)
        .exclude(team_id__in=_source_rows().values("team_id"))
    )
    if team_ids is not None:
        configs = configs.filter(team_id__in=team_ids)
    if after_team_id is not None:
        configs = configs.filter(team_id__gt=after_team_id)
    return list(configs.order_by("team_id").values_list("team_id", flat=True)[:limit])


def enable_analytics_source(team_id: int) -> bool:
    """Write the backfill row for one team. False when the team has a row already."""
    source_product, source_type = ALERT_SCOPE_SOURCE
    # The unique constraint on the source keys stops a second row when a person's toggle writes one at the same time.
    _, created = SignalSourceConfig.objects.get_or_create(
        team_id=team_id,
        source_product=source_product,
        source_type=source_type,
        defaults={"enabled": True, "config": dict(BACKFILL_CONFIG)},
    )
    if created:
        logger.info("anomaly_scoring_analytics_source_backfilled", team_id=team_id)
    return created


def backfill_analytics_sources(
    *,
    apply: bool,
    team_ids: list[int] | None,
    batch_size: int,
    on_batch: Callable[[int], None] | None = None,
) -> BackfillSummary:
    summary = BackfillSummary()
    scoring_config = read_config(read_payload())
    scanned = 0
    # A team id cursor rather than re-reading the first page: in a dry run, every team still matches.
    after_team_id = None
    while True:
        batch = self_driving_team_ids_without_source(team_ids=team_ids, after_team_id=after_team_id, limit=batch_size)
        if not batch:
            return summary
        teams = Team.objects.filter(id__in=batch).only("id", "organization_id")
        summary.matched += len(batch)
        summary.in_rollout += sum(1 for team in teams if enrolls_team(scoring_config, team))
        summary.team_ids.extend(batch)
        if apply:
            for team_id in batch:
                if enable_analytics_source(team_id):
                    summary.created += 1
                else:
                    summary.not_created += 1
        scanned += len(batch)
        after_team_id = batch[-1]
        if on_batch is not None:
            on_batch(scanned)


def _unchanged(row: SignalSourceConfig) -> bool:
    # Onboarding and the product toggles set `created_by` on enable. The settings page changes `config` or `enabled`.
    return row.created_by_id is None and row.enabled and row.config == BACKFILL_CONFIG


def revert_analytics_source(*, team_id: int, row_id: UUID) -> bool:
    """Delete one backfill row. False when the row changed or went away after the read."""
    with transaction.atomic():
        row = SignalSourceConfig.objects.select_for_update().filter(team_id=team_id, pk=row_id).first()
        if row is None or not _unchanged(row):
            return False
        row.delete()
    logger.info("anomaly_scoring_analytics_source_backfill_reverted", team_id=row.team_id)
    return True


def revert_analytics_sources(*, apply: bool, team_ids: list[int] | None) -> RevertSummary:
    """Delete the rows that the backfill wrote and nobody changed since."""
    summary = RevertSummary()
    rows = _source_rows(team_ids).filter(config__contains={BACKFILL_MARKER_KEY: BACKFILL_MARKER}).order_by("team_id")
    for row in rows.iterator():
        summary.matched += 1
        if not _unchanged(row):
            summary.skipped_changed += 1
            continue
        summary.team_ids.append(row.team_id)
        if not apply:
            continue
        if revert_analytics_source(team_id=row.team_id, row_id=row.pk):
            summary.deleted += 1
        else:
            summary.skipped_changed += 1
    return summary
