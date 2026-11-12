"""Schemas PostHog stopped syncing itself after an error that retrying would not fix, and turning them back on.

`auto_disabled_at` tells these apart from schemas the user turned off or that discovery left off. Only a schema
with the stamp set is ever listed here.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, QuerySet
from django.db.models.functions import Left
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.facade.contracts import (
    AutoDisabledErrorGroup,
    AutoDisabledSchemaFilter,
    AutoDisabledSchemaRow,
    AutoDisabledSchemaSelection,
    AutoDisabledSchemasPage,
    AutoDisabledSchemasSummary,
    SchemaReenableResult,
    SchemaReenableTarget,
)
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema, update_should_sync

logger = structlog.get_logger(__name__)

DEFAULT_DAYS = 7
DAYS_CHOICES = (1, 3, 7, 14, 30)
# Each re-enable runs `update_should_sync`: about four Postgres queries, two new Temporal connections and two
# Temporal calls. At a few hundred milliseconds each, 200 schemas finish in about a minute, inside one request.
MAX_REENABLE_PER_RUN = 200
# The console stops starting re-enables after this long. Envoy cuts a response on /admin/ at 300 seconds and the
# ALB idles out at 300 seconds, so this leaves room for the last call and the result page when Temporal is slow.
REENABLE_TIME_BUDGET_SECONDS = 180
SCHEMAS_PER_PAGE = 50
# Grouping reads one row per schema. Past this many, the groups cover only the newest schemas.
MAX_GROUPED_SCHEMAS = 50_000
ERROR_GROUP_LENGTH = 80
# A cut shorter than this keeps too little of the error to tell causes apart, so the whole first line is used.
MIN_ERROR_GROUP_LENGTH = 24
# Grouping looks at the start of the error only, so the query reads no more than this.
ERROR_READ_LENGTH = 500

_VARIABLE_TOKEN = re.compile(r"\S*\d")


def error_group(error: str | None) -> str:
    """The start of the error that errors of one cause share.

    The result is a substring of the error, so it also works as the error filter that finds the whole group.
    It cuts at the first word with a digit, because IDs, hosts, ports and counts vary between schemas.
    """
    if not error:
        return ""
    lines = error.strip().splitlines()
    first_line = lines[0] if lines else ""
    variable = _VARIABLE_TOKEN.search(first_line)
    if variable is not None and variable.start() >= MIN_ERROR_GROUP_LENGTH:
        first_line = first_line[: variable.start()]
    return first_line[:ERROR_GROUP_LENGTH].rstrip()


def _matching(selection: AutoDisabledSchemaFilter) -> QuerySet[ExternalDataSchema]:
    schemas = ExternalDataSchema.objects.filter(
        should_sync=False,
        auto_disabled_at__isnull=False,
        auto_disabled_at__gte=timezone.now() - timedelta(days=selection.days),
    ).exclude(deleted=True)
    if selection.source_type:
        schemas = schemas.filter(source__source_type=selection.source_type)
    if selection.error:
        schemas = schemas.filter(latest_error__icontains=selection.error)
    if selection.team_id is not None:
        schemas = schemas.filter(team_id=selection.team_id)
    return schemas


def _newest_first(selection: AutoDisabledSchemaFilter) -> QuerySet[ExternalDataSchema]:
    return (
        _matching(selection)
        .select_related(None)
        .select_related("source")
        .only("id", "name", "team_id", "source_id", "source__source_type", "auto_disabled_at", "latest_error")
        .order_by("-auto_disabled_at", "id")
    )


@frozen(frozen=False)
class _GroupTally:
    count: int
    newest_at: datetime
    oldest_at: datetime


def _row(schema: ExternalDataSchema) -> AutoDisabledSchemaRow:
    assert schema.auto_disabled_at is not None
    return AutoDisabledSchemaRow(
        id=schema.id,
        name=schema.name,
        team_id=schema.team_id,
        source_id=schema.source_id,
        source_type=schema.source.source_type,
        auto_disabled_at=schema.auto_disabled_at,
        latest_error=schema.latest_error,
    )


class AutoDisabledSchemas:
    @staticmethod
    def summary(selection: AutoDisabledSchemaFilter) -> AutoDisabledSchemasSummary:
        schemas = _matching(selection)
        totals = schemas.aggregate(
            total=Count("id"),
            teams=Count("team_id", distinct=True),
            sources=Count("source_id", distinct=True),
        )
        groups: dict[tuple[str, str], _GroupTally] = {}
        grouped_count = 0
        newest = (
            schemas.order_by("-auto_disabled_at")
            .annotate(error_start=Left("latest_error", ERROR_READ_LENGTH))
            .values_list("source__source_type", "error_start", "auto_disabled_at")[:MAX_GROUPED_SCHEMAS]
        )
        for source_type, error_start, auto_disabled_at in newest:
            if auto_disabled_at is None:
                # The filter already excludes these. The check narrows the type.
                continue
            grouped_count += 1
            key = (source_type, error_group(error_start))
            tally = groups.get(key)
            if tally is None:
                # Rows arrive newest first, so the first row of a group is its newest.
                groups[key] = _GroupTally(count=1, newest_at=auto_disabled_at, oldest_at=auto_disabled_at)
            else:
                tally.count += 1
                tally.oldest_at = auto_disabled_at
        ordered = sorted(groups.items(), key=lambda item: (-item[1].count, item[0]))
        return AutoDisabledSchemasSummary(
            total=totals["total"],
            team_count=totals["teams"],
            source_count=totals["sources"],
            groups=tuple(
                AutoDisabledErrorGroup(
                    source_type=source_type,
                    error=error,
                    count=tally.count,
                    newest_at=tally.newest_at,
                    oldest_at=tally.oldest_at,
                )
                for (source_type, error), tally in ordered
            ),
            grouped_count=grouped_count,
        )

    @staticmethod
    def page(selection: AutoDisabledSchemaFilter, page_number: str | None) -> AutoDisabledSchemasPage:
        page = Paginator(_newest_first(selection), SCHEMAS_PER_PAGE).get_page(page_number)
        return AutoDisabledSchemasPage(
            rows=tuple(_row(schema) for schema in page),
            number=page.number,
            num_pages=page.paginator.num_pages,
            count=page.paginator.count,
        )

    @staticmethod
    def select(selection: AutoDisabledSchemaFilter) -> AutoDisabledSchemaSelection:
        schemas = _newest_first(selection)
        rows = tuple(_row(schema) for schema in schemas[:MAX_REENABLE_PER_RUN])
        total = len(rows) if len(rows) < MAX_REENABLE_PER_RUN else schemas.count()
        return AutoDisabledSchemaSelection(rows=rows, total=total)

    @staticmethod
    def reenable(
        targets: Sequence[SchemaReenableTarget], time_budget_seconds: float | None = None
    ) -> SchemaReenableResult:
        """Turns syncing on for each target that is still off, not deleted, and has the stop time staff saw.

        A failure on one schema is logged and reported, its change is rolled back, and the others still run. With
        a time budget, targets not started when it runs out are returned as not attempted, and nothing is done to
        them.
        """
        reenabled: list[UUID] = []
        skipped: list[UUID] = []
        failed: list[UUID] = []
        not_attempted: list[UUID] = []
        deadline = monotonic() + time_budget_seconds if time_budget_seconds is not None else None
        for target in targets:
            if deadline is not None and monotonic() >= deadline:
                not_attempted.append(target.schema_id)
                continue
            try:
                with transaction.atomic():
                    # The row lock holds from the check to the save, so a customer who deletes or turns off the
                    # schema in between waits, and their change lands after this one instead of being overwritten.
                    # The tool sends only stamped targets, and a stamp never equals null, so it cannot turn on a
                    # schema the user turned off. The command also sends null stamps, for schemas it matched by
                    # error alone. A Temporal failure inside rolls the save back.
                    unchanged = (
                        ExternalDataSchema.objects.select_for_update()
                        .filter(
                            id=target.schema_id,
                            team_id=target.team_id,
                            should_sync=False,
                            auto_disabled_at=target.auto_disabled_at,
                        )
                        .exclude(deleted=True)
                        .only("id")
                        .first()
                    )
                    if unchanged is None:
                        skipped.append(target.schema_id)
                        continue
                    update_should_sync(schema_id=str(target.schema_id), team_id=target.team_id, should_sync=True)
            except Exception:
                logger.exception(
                    "auto_disabled_schema_reenable_failed", schema_id=str(target.schema_id), team_id=target.team_id
                )
                failed.append(target.schema_id)
                continue
            logger.info("auto_disabled_schema_reenabled", schema_id=str(target.schema_id), team_id=target.team_id)
            reenabled.append(target.schema_id)
        if not_attempted:
            logger.warning("auto_disabled_schema_reenable_out_of_time", not_attempted=len(not_attempted))
        return SchemaReenableResult(
            reenabled=tuple(reenabled),
            skipped=tuple(skipped),
            failed=tuple(failed),
            not_attempted=tuple(not_attempted),
        )
