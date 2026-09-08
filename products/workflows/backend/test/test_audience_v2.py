from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from posthog.hogql.query import execute_hogql_query

from products.feature_flags.backend.user_blast_radius import get_user_blast_radius
from products.workflows.backend.services.audience_v2 import (
    bounded_memory_settings,
    build_person_count_query,
    get_person_audience_count_v2,
)

FILTERS = {"properties": [{"key": "subscribed", "type": "person", "value": ["true"], "operator": "exact"}]}


class TestAudienceV2(ClickhouseTestMixin, BaseTest):
    def _create_persons(self, subscribed_flags: list[bool]) -> None:
        for i, subscribed in enumerate(subscribed_flags, start=1):
            _create_person(
                team=self.team,
                distinct_ids=[f"user-{i}"],
                properties={"subscribed": "true" if subscribed else "false"},
            )
        flush_persons_and_events()

    def test_small_audience_falls_back_to_exact_count_and_matches_v1(self):
        # A handful of persons never clears MIN_SAMPLED_MATCHES under the default 1-in-64
        # sample, so this exercises the exact fallback and pins it to the v1 result.
        self._create_persons([True, True, True, False])

        result = get_person_audience_count_v2(self.team, FILTERS)
        v1_result = get_user_blast_radius(self.team, FILTERS)

        assert (result.affected, result.total) == (3, 4)
        assert (result.affected, result.total) == (v1_result.affected, v1_result.total)

    def test_sampled_path_extrapolates_by_modulus(self):
        self._create_persons([True, True, False])

        # Modulus 1 samples everyone and MIN_SAMPLED_MATCHES 0 forces the sampled branch,
        # so the extrapolated result must equal the exact count.
        with (
            patch("products.workflows.backend.services.audience_v2.SAMPLE_MODULUS", 1),
            patch("products.workflows.backend.services.audience_v2.MIN_SAMPLED_MATCHES", 0),
        ):
            result = get_person_audience_count_v2(self.team, FILTERS)

        assert (result.affected, result.total) == (2, 3)

    def test_no_filters_returns_total_for_everyone(self):
        self._create_persons([True, False])

        result = get_person_audience_count_v2(self.team, {})

        assert (result.affected, result.total) == (2, 2)

    def test_sampling_predicate_reaches_raw_person_prefilter(self):
        # The memory bound depends on WhereClauseExtractor pushing the call-form sampling
        # predicate into the raw person scan. If that push stops (for example the predicate
        # becomes an arithmetic node, which the extractor refuses), the sampled query
        # silently degrades to a full-team dedup and large teams hit the memory limit again.
        query = build_person_count_query(self.team, None, sample_modulus=64)
        response = execute_hogql_query(query=query, team=self.team, settings=bounded_memory_settings())

        clickhouse_sql = response.clickhouse
        assert clickhouse_sql is not None
        assert "AS where_optimization" in clickhouse_sql
        inner_scan = clickhouse_sql.split("AS where_optimization", 1)[1]
        assert "cityHash64" in inner_scan
        assert "optimize_aggregation_in_order" in clickhouse_sql
        assert "max_bytes_before_external_group_by=4294967296" in clickhouse_sql
