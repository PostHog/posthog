from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.clickhouse.query_tagging import Feature, tags_context
from posthog.hogql_queries.query_runner import ExecutionMode

from products.experiments.backend.hogql_queries.experiment_lazy_precompute import (
    CANARY_TRIGGER,
    STALE_WHILE_REVALIDATE_SECONDS,
    TIMESERIES_BACKFILL_TRIGGER,
    TIMESERIES_WARMING_TRIGGER,
    experiment_ensure_precomputed,
)
from products.experiments.backend.hogql_queries.experiment_query_runner import (
    RESULT_CACHE_MAX_AGE,
    ExperimentResultsCacheMixin,
)


class TestExperimentServeStalePolicy(BaseTest):
    def _grace_for(self, **tags) -> float | None:
        self.team._experiments_serve_stale_flag = True  # type: ignore[attr-defined]
        with (
            tags_context(**tags),
            patch(
                "products.experiments.backend.hogql_queries.experiment_lazy_precompute.ensure_precomputed"
            ) as mock_ensure,
        ):
            experiment_ensure_precomputed(team=self.team, insert_query="SELECT 1")
        return mock_ensure.call_args.kwargs["stale_while_revalidate_seconds"]

    def test_user_facing_read_takes_the_grace(self):
        assert self._grace_for(trigger="query") == STALE_WHILE_REVALIDATE_SECONDS

    @parameterized.expand(
        [
            (TIMESERIES_WARMING_TRIGGER,),
            (TIMESERIES_BACKFILL_TRIGGER,),
            (CANARY_TRIGGER,),
        ]
    )
    def test_refresher_takes_no_grace_so_it_never_serves_itself_stale(self, trigger: str):
        assert self._grace_for(trigger=trigger) is None

    @parameterized.expand(
        [
            (ExecutionMode.CALCULATE_BLOCKING_ALWAYS.value,),
            (ExecutionMode.CALCULATE_ASYNC_ALWAYS.value,),
        ]
    )
    def test_forced_refresh_takes_no_grace(self, execution_mode: str):
        assert self._grace_for(trigger="query", execution_mode=execution_mode) is None

    def test_cache_warmup_feature_takes_no_grace(self):
        assert self._grace_for(trigger="something/unnamed", feature=Feature.CACHE_WARMUP) is None

    def test_flag_off_keeps_the_inline_rebuild(self):
        self.team._experiments_serve_stale_flag = False  # type: ignore[attr-defined]
        with patch(
            "products.experiments.backend.hogql_queries.experiment_lazy_precompute.ensure_precomputed"
        ) as mock_ensure:
            experiment_ensure_precomputed(team=self.team, insert_query="SELECT 1")
        assert mock_ensure.call_args.kwargs["stale_while_revalidate_seconds"] is None


class TestExperimentResultsCacheMixin(SimpleTestCase):
    @parameterized.expand(
        [
            ("just under a day", timedelta(hours=23), False),
            ("the warmer has not come round yet", timedelta(hours=25), False),
            ("well past the next warm", timedelta(hours=27), True),
        ]
    )
    def test_staleness_spans_the_warming_cadence(self, _name: str, age: timedelta, expected_stale: bool):
        mixin = ExperimentResultsCacheMixin()
        last_refresh = datetime.now(UTC) - age

        assert mixin._is_stale(last_refresh) is expected_stale
        assert mixin.cache_target_age(last_refresh) == last_refresh + RESULT_CACHE_MAX_AGE

    def test_no_last_refresh_is_stale(self):
        mixin = ExperimentResultsCacheMixin()

        assert mixin._is_stale(None) is True
        assert mixin.cache_target_age(None) is None
