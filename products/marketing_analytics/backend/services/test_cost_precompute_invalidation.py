from datetime import UTC, date, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from products.analytics_platform.backend.models import PreaggregationJob
from products.marketing_analytics.backend.services.cost_precompute_invalidation import (
    COST_MATERIALIZATION_GRAINS,
    cost_query_hash,
    invalidate_cost_precompute,
    iter_cost_materializations,
    resolve_cost_query_hashes,
    utc_day_bounds,
)

_SERVICE = "products.marketing_analytics.backend.services.cost_precompute_invalidation"
_DB = f"{_SERVICE}.Database"
_FACTORY = f"{_SERVICE}.MarketingSourceFactory"


def _insert_query(source_id: str, grain) -> ast.SelectQuery:
    """Stand-in for a real materialization query. Shape doesn't matter, but it must be a resolvable
    SelectQuery and must vary by (source, grain) the way a real one does — the adapter is built with
    the grain in its QueryContext and selects grain-specific columns, so each grain is its own hash.

    Built as AST rather than parsed from a string: interpolating the source id into HogQL text trips
    `hogql-fstring-audit`, and the rule is right to be blunt about it even in a test. Constructing the
    nodes keeps `time_window_min` an unresolved Placeholder, which parsing with partial placeholders
    could not — `replace_placeholders` evaluates every placeholder it walks, so passing only some fails.
    """
    return ast.SelectQuery(
        select=[
            ast.Alias(alias="source_id", expr=ast.Constant(value=source_id)),
            ast.Alias(alias="grain", expr=ast.Constant(value=grain.value)),
            ast.Alias(alias="cost_date", expr=ast.Placeholder(expr=ast.Field(chain=["time_window_min"]))),
        ]
    )


class CostPrecomputeInvalidationTest(APIBaseTest):
    def _fake_adapter(self, source_id: str, grain, *, materializable: bool = True) -> MagicMock:
        adapter = MagicMock()
        adapter.get_source_id.return_value = source_id
        adapter.supports_level.return_value = True
        adapter.build_materialization_query.side_effect = (
            (lambda sid: _insert_query(sid, grain)) if materializable else (lambda sid: None)
        )
        return adapter

    def _fake_factory(self, adapters: list) -> MagicMock:
        factory = MagicMock()
        factory.create_adapters.return_value = adapters
        factory.get_valid_adapters.side_effect = lambda a: a
        return factory

    def _patched(self, source_ids=("src1",), *, materializable: bool = True):
        """Patch the factory per grain, as production does: the service builds a fresh
        MarketingSourceFactory from a QueryContext carrying the grain, once per grain."""
        self.adapters: dict = {}

        def make_factory(context):
            grain = context.drill_down_level
            adapters = [self._fake_adapter(sid, grain, materializable=materializable) for sid in source_ids]
            for sid, adapter in zip(source_ids, adapters):
                self.adapters[(sid, grain)] = adapter
            return self._fake_factory(adapters)

        return (patch(_DB, MagicMock()), patch(_FACTORY, side_effect=make_factory))

    def _job(self, query_hash: str, start_day: int, end_day: int) -> PreaggregationJob:
        return PreaggregationJob.objects.create(
            team=self.team,
            query_hash=query_hash,
            time_range_start=datetime(2026, 7, start_day, tzinfo=UTC),
            time_range_end=datetime(2026, 7, end_day, tzinfo=UTC),
            status=PreaggregationJob.Status.READY,
            expires_at=datetime(2026, 7, 30, tzinfo=UTC) + timedelta(days=7),
        )

    # --- Enumeration ---

    def test_enumerates_every_grain_for_a_source(self):
        db, factory = self._patched()
        with db, factory:
            materializations = list(iter_cost_materializations(self.team))

        assert len(materializations) == len(COST_MATERIALIZATION_GRAINS)
        assert {m.grain for m in materializations} == set(COST_MATERIALIZATION_GRAINS)

    def test_skips_unmaterializable_sources(self):
        db, factory = self._patched(materializable=False)
        with db, factory:
            assert list(iter_cost_materializations(self.team)) == []

    def test_each_grain_gets_its_own_hash(self):
        """A source materializes separately per grain, so collapsing hashes by source would strand
        two of the three grains' jobs on every invalidation."""
        db, factory = self._patched()
        with db, factory:
            hashes = resolve_cost_query_hashes(self.team)

        assert len(hashes) == len(COST_MATERIALIZATION_GRAINS)
        assert len(set(hashes)) == len(COST_MATERIALIZATION_GRAINS)

    def test_hashes_are_stable_across_calls(self):
        # Invalidation only works because it re-derives the same hash the warmer wrote.
        db, factory = self._patched()
        with db, factory:
            first = resolve_cost_query_hashes(self.team)
        db, factory = self._patched()
        with db, factory:
            second = resolve_cost_query_hashes(self.team)

        assert first == second

    def test_different_sources_hash_differently(self):
        db, factory = self._patched(("src_a", "src_b"))
        with db, factory:
            hashes = resolve_cost_query_hashes(self.team)

        assert len(set(hashes)) == 2 * len(COST_MATERIALIZATION_GRAINS)

    def test_hash_is_none_when_source_stops_being_materializable(self):
        # Enumeration probes, then hashing rebuilds — a source can break in between.
        db, factory = self._patched()
        with db, factory:
            materialization = next(iter(iter_cost_materializations(self.team)))
            self.adapters[
                (materialization.source_id, materialization.grain)
            ].build_materialization_query.side_effect = lambda sid: None
            assert cost_query_hash(self.team, materialization) is None

    # --- Invalidation ---

    def test_invalidates_only_jobs_carrying_a_derived_hash(self):
        db, factory = self._patched()
        with db, factory:
            hashes = resolve_cost_query_hashes(self.team)
            mine = [self._job(h, 16, 17) for h in hashes]
            unrelated = self._job("some_other_products_hash", 16, 17)

            invalidation = invalidate_cost_precompute(self.team, date(2026, 7, 16), date(2026, 7, 18))

        assert invalidation.query_hashes_resolved == len(hashes)
        assert invalidation.sources_resolved == 1
        assert invalidation.result.jobs_deleted == len(mine)
        assert not PreaggregationJob.objects.filter(id__in=[j.id for j in mine]).exists()
        assert PreaggregationJob.objects.filter(id=unrelated.id).exists()

    def test_leaves_jobs_outside_the_range(self):
        db, factory = self._patched()
        with db, factory:
            hashes = resolve_cost_query_hashes(self.team)
            inside = self._job(hashes[0], 16, 17)
            outside = self._job(hashes[0], 25, 26)

            invalidate_cost_precompute(self.team, date(2026, 7, 16), date(2026, 7, 18))

        assert not PreaggregationJob.objects.filter(id=inside.id).exists()
        assert PreaggregationJob.objects.filter(id=outside.id).exists()

    def test_no_derivable_sources_reports_nothing_invalidated(self):
        """Empty hashes must not read as success — it's indistinguishable from a broken source, and
        deleting nothing while returning 200 would look like the rebuild was scheduled."""
        db, factory = self._patched(materializable=False)
        with db, factory:
            self._job("orphaned_hash", 16, 17)
            invalidation = invalidate_cost_precompute(self.team, date(2026, 7, 16), date(2026, 7, 18))

        assert invalidation.query_hashes_resolved == 0
        assert invalidation.sources_resolved == 0
        assert invalidation.result.jobs_deleted == 0

    def test_dry_run_leaves_jobs_alone(self):
        db, factory = self._patched()
        with db, factory:
            hashes = resolve_cost_query_hashes(self.team)
            job = self._job(hashes[0], 16, 17)

            invalidation = invalidate_cost_precompute(self.team, date(2026, 7, 16), date(2026, 7, 18), dry_run=True)

        assert invalidation.result.jobs_deleted == 1
        assert PreaggregationJob.objects.filter(id=job.id).exists()

    def test_reports_effective_range_wider_than_requested(self):
        db, factory = self._patched()
        with db, factory:
            hashes = resolve_cost_query_hashes(self.team)
            self._job(hashes[0], 1, 31)  # one wide job swallowing the requested days

            invalidation = invalidate_cost_precompute(self.team, date(2026, 7, 16), date(2026, 7, 18))

        assert invalidation.result.effective_start == datetime(2026, 7, 1, tzinfo=UTC)
        assert invalidation.result.effective_end == datetime(2026, 7, 31, tzinfo=UTC)


class UtcDayBoundsTest(APIBaseTest):
    def test_covers_both_endpoint_days(self):
        start, end = utc_day_bounds(date(2026, 7, 16), date(2026, 7, 18))

        assert start == datetime(2026, 7, 16, tzinfo=UTC)
        # Half-open, so the 18th has to be fully inside.
        assert end == datetime(2026, 7, 19, tzinfo=UTC)

    def test_single_day_is_not_empty(self):
        start, end = utc_day_bounds(date(2026, 7, 16), date(2026, 7, 16))

        assert start < end
        assert end - start == timedelta(days=1)
