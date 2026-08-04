"""Invalidate and rebuild the native cost precompute for a date range.

`PreaggregationJob` has no product, table or source column, and `compute_query_hash` deliberately
excludes the table, so there is no way to ask Postgres "which jobs belong to marketing costs?". The
only handle on a job is its query hash, so invalidation has to *re-derive* the hashes the warmer and
the read path would produce, then delete the jobs carrying them. That makes the enumeration below
load-bearing: it must stay identical to what materializes the data, which is why the Dagster warmer
drives the same iterator instead of keeping its own copy.

Two limits are inherent to re-derivation and can't be closed here:

- If team config changed since a job was created (`campaign_field_preferences`, `base_currency`,
  timezone), the old hash is unrecoverable. This is self-consistent — the read path derives the same
  new hash and can't find those jobs either, so they are already dead and age out on their TTL.
- A source broken enough that `build_materialization_query` returns None has no derivable hash, so
  its jobs can't be invalidated through here. That is the case the management command exists for.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog

from posthog.schema import MarketingAnalyticsDrillDownLevel

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team

from posthog.models import Team
from posthog.models.team.team import DEFAULT_CURRENCY

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    InvalidationResult,
    LazyComputationTable,
    build_precompute_query_info,
    compute_query_hash,
    invalidate_jobs,
)
from products.marketing_analytics.backend.hogql_queries.adapters.base import QueryContext
from products.marketing_analytics.backend.hogql_queries.adapters.factory import MarketingSourceFactory

logger = structlog.get_logger(__name__)

# Costs are materialized per grain because the source tables aren't roll-ups of each other (a
# campaign-stats row is not the sum of its ads), so each grain is its own job and its own hash.
COST_MATERIALIZATION_GRAINS = (
    MarketingAnalyticsDrillDownLevel.CAMPAIGN,
    MarketingAnalyticsDrillDownLevel.AD_GROUP,
    MarketingAnalyticsDrillDownLevel.AD,
)


@dataclass
class CostMaterialization:
    """One (source, grain) pair that materializes into the native cost table.

    `build_query` is a fresh callable rather than a built AST because the executor resolves time
    placeholders in place, so each window needs its own copy. The job hash is deliberately not a
    field: the warmer iterates these on a schedule and never needs one, so deriving it here would
    make every warm run pay for a resolve it throws away. Hashing is `cost_query_hash`'s job.
    """

    grain: MarketingAnalyticsDrillDownLevel
    source_id: str
    build_query: Callable[[], ast.SelectQuery | None]


def iter_cost_materializations(
    team: Team,
    grains: tuple[MarketingAnalyticsDrillDownLevel, ...] = COST_MATERIALIZATION_GRAINS,
) -> Iterator[CostMaterialization]:
    """Every (source, grain) pair that can materialize costs for this team, with its job hash.

    Built userless with warehouse access control bypassed, matching how the materialization INSERT is
    printed — anything narrower yields a different adapter set, and therefore hashes that don't match
    the jobs actually on disk. Sources that can't build a materialization query are skipped: that is
    deterministic per source rather than per window, so probing once is enough.
    """
    # Database.create_for is ~550ms; build once and share across grains and sources for this team.
    database = Database.create_for(
        team=team,
        modifiers=create_default_modifiers_for_team(team),
        bypass_warehouse_access_control=True,
    )
    base_currency = team.base_currency or DEFAULT_CURRENCY

    for grain in grains:
        ctx = QueryContext(
            date_range=None,  # materialization filters on time_window placeholders, not the range
            team=team,
            base_currency=base_currency,
            drill_down_level=grain,
            database=database,
        )
        factory = MarketingSourceFactory(context=ctx)
        adapters = [a for a in factory.get_valid_adapters(factory.create_adapters()) if a.supports_level(grain)]
        for adapter in adapters:
            source_id = adapter.get_source_id()

            def build_query(adapter=adapter, source_id=source_id) -> ast.SelectQuery | None:
                return adapter.build_materialization_query(source_id)

            if build_query() is None:
                logger.info(
                    "marketing_cost_materialization_skipped",
                    team_id=team.pk,
                    grain=grain.value,
                    source_id=source_id,
                    reason="unmaterializable",
                )
                continue

            yield CostMaterialization(grain=grain, source_id=source_id, build_query=build_query)


def cost_query_hash(team: Team, materialization: CostMaterialization) -> str | None:
    """The `PreaggregationJob.query_hash` this materialization's jobs carry, or None if the source
    stopped being materializable between enumeration and here."""
    query = materialization.build_query()
    if query is None:
        return None
    return compute_query_hash(
        build_precompute_query_info(
            team=team,
            insert_query=query,
            table=LazyComputationTable.MARKETING_COSTS_PREAGGREGATED,
        )
    )


def resolve_cost_query_hashes(
    team: Team,
    grains: tuple[MarketingAnalyticsDrillDownLevel, ...] = COST_MATERIALIZATION_GRAINS,
) -> list[str]:
    """The job hashes for this team's cost precompute. Empty means nothing is derivable — treat that
    as "invalidated nothing" rather than success, since it's indistinguishable from a broken source."""
    hashes = (cost_query_hash(team, m) for m in iter_cost_materializations(team, grains))
    return [h for h in hashes if h is not None]


def utc_day_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Half-open [start, end) covering both endpoint days.

    UTC, not the team timezone: precompute windows are UTC-aligned, and job overlap is inclusive, so
    interpreting the request in UTC can only widen what's matched — never miss a job the caller meant.
    """
    return (
        datetime(date_from.year, date_from.month, date_from.day, tzinfo=UTC),
        datetime(date_to.year, date_to.month, date_to.day, tzinfo=UTC) + timedelta(days=1),
    )


@dataclass
class CostInvalidation:
    """Aggregate counts only — never per-source detail.

    Hashes are derived with warehouse access control bypassed (they must be, to match the jobs on
    disk), so a user without access to a given source can still invalidate its jobs. Invalidation
    isn't a data read, and withholding the breakdown keeps it from leaking which sources exist.
    """

    sources_resolved: int
    query_hashes_resolved: int
    result: InvalidationResult


def invalidate_cost_precompute(
    team: Team,
    date_from: date,
    date_to: date,
    grains: tuple[MarketingAnalyticsDrillDownLevel, ...] = COST_MATERIALIZATION_GRAINS,
    dry_run: bool = False,
) -> CostInvalidation:
    """Drop the cost precompute jobs covering [date_from, date_to] so the next read recomputes them."""
    materializations = list(iter_cost_materializations(team, grains))
    # One hash per (source, grain) — a source materializes separately at each grain, so keying this
    # by source alone would collapse three hashes into one and leave two grains stranded.
    hashes = [h for h in (cost_query_hash(team, m) for m in materializations) if h is not None]
    start, end = utc_day_bounds(date_from, date_to)

    if not hashes:
        return CostInvalidation(
            sources_resolved=0,
            query_hashes_resolved=0,
            result=InvalidationResult(jobs_deleted=0, effective_start=None, effective_end=None),
        )

    result = invalidate_jobs(team=team, query_hashes=hashes, start=start, end=end, dry_run=dry_run)
    logger.info(
        "marketing_cost_precompute_invalidated",
        team_id=team.pk,
        date_from=str(date_from),
        date_to=str(date_to),
        dry_run=dry_run,
        query_hashes=len(hashes),
        jobs_deleted=result.jobs_deleted,
        effective_start=str(result.effective_start),
        effective_end=str(result.effective_end),
    )
    return CostInvalidation(
        sources_resolved=len({m.source_id for m in materializations}),
        query_hashes_resolved=len(hashes),
        result=result,
    )
