from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_person, flush_persons_and_events
from unittest.mock import patch

from posthog.hogql.query import execute_hogql_query

from products.cohorts.backend.models.cohort import Cohort
from products.feature_flags.backend.user_blast_radius import get_user_blast_radius, replace_proxy_properties
from products.workflows.backend.services.audience_v2 import (
    bounded_memory_settings,
    build_dedupe_count_query,
    build_person_count_query,
    get_dedupe_audience_count_v2,
    get_person_audience_count_v2,
)
from products.workflows.backend.services.batch_audience import get_batch_audience_count

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

    def test_person_whose_latest_version_no_longer_matches_is_excluded(self):
        # The id prefilter matches any row version, but only the latest version decides
        # membership. A person updated from subscribed=true to false must not count.
        churned_uuid = "01970000-0000-0000-0000-0000000000a1"
        _create_person(
            team=self.team,
            distinct_ids=["churned"],
            uuid=churned_uuid,
            properties={"subscribed": "true"},
            version=0,
        )
        _create_person(
            team=self.team,
            distinct_ids=["churned-v1"],
            uuid=churned_uuid,
            properties={"subscribed": "false"},
            version=1,
        )
        _create_person(team=self.team, distinct_ids=["kept"], properties={"subscribed": "true"})
        flush_persons_and_events()

        result = get_person_audience_count_v2(self.team, FILTERS)

        assert (result.affected, result.total) == (1, 2)

    def test_distinct_id_filter_counts_a_person_with_several_aliases_once(self):
        # A `distinct_id` person property resolves through the persons.pdi join, which gives a
        # person one row per distinct id. Both count branches must dedup on the person id, or
        # the preview reports more sends than the enumeration produces.
        _create_person(team=self.team, distinct_ids=["alias-a", "alias-b"], properties={"subscribed": "true"})
        _create_person(team=self.team, distinct_ids=["other"], properties={"subscribed": "true"})
        flush_persons_and_events()

        filters = {
            "properties": [
                {"key": "distinct_id", "type": "person", "value": ["alias-a", "alias-b"], "operator": "exact"}
            ]
        }

        result = get_person_audience_count_v2(self.team, filters)
        v1_result = get_user_blast_radius(self.team, filters)

        assert (result.affected, result.total) == (1, 2)
        assert (result.affected, result.total) == (v1_result.affected, v1_result.total)

        with (
            patch("products.workflows.backend.services.audience_v2.SAMPLE_MODULUS", 1),
            patch("products.workflows.backend.services.audience_v2.MIN_SAMPLED_MATCHES", 0),
        ):
            sampled_result = get_person_audience_count_v2(self.team, filters)

        assert (sampled_result.affected, sampled_result.total) == (1, 2)

    def test_cohort_filter_matches_v1(self):
        # Cohort filters compile to a different subquery shape than plain property filters,
        # so the sampled query and the bounded settings must not break them.
        for i in range(6):
            _create_person(team=self.team, distinct_ids=[f"cohort-user-{i}"], properties={"group": str(i)})
        flush_persons_and_events()
        cohort = Cohort.objects.create(
            team=self.team,
            name="cohort1",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "OR", "values": [{"key": "group", "value": ["1", "2", "3"], "type": "person"}]}
                    ],
                }
            },
        )
        filters = {"properties": [{"key": "id", "type": "cohort", "value": cohort.pk}]}

        result = get_person_audience_count_v2(self.team, filters)
        v1_result = get_user_blast_radius(self.team, filters)

        assert (result.affected, result.total) == (3, 6)
        assert (result.affected, result.total) == (v1_result.affected, v1_result.total)

        cohort.calculate_people_ch(pending_version=0)
        with self.settings(USE_PRECALCULATED_CH_COHORT_PEOPLE=True):
            result = get_person_audience_count_v2(self.team, filters)

        assert (result.affected, result.total) == (3, 6)

    def test_dedupe_count_matches_v1(self):
        # Duplicate emails (case/whitespace variants) collapse to one send group; persons
        # without an email keep their own group. Small data exercises the exact fallback.
        emails = ["Dup@X.com", " dup@x.com ", "b@x.com", None, ""]
        for i, email in enumerate(emails, start=1):
            properties: dict = {"subscribed": "true"}
            if email is not None:
                properties["email"] = email
            _create_person(team=self.team, distinct_ids=[f"user-{i}"], properties=properties)
        flush_persons_and_events()

        result = get_dedupe_audience_count_v2(self.team, FILTERS, "email")

        assert result.affected == get_batch_audience_count(self.team, FILTERS, dedupe_key="email") == 4
        assert result.total == 5

    def test_sampled_dedupe_count_extrapolates_by_modulus(self):
        for i in range(3):
            _create_person(
                team=self.team,
                distinct_ids=[f"user-{i}"],
                properties={"subscribed": "true", "email": f"user-{i}@example.com"},
            )
        flush_persons_and_events()

        with (
            patch("products.workflows.backend.services.audience_v2.SAMPLE_MODULUS", 1),
            patch("products.workflows.backend.services.audience_v2.MIN_SAMPLED_MATCHES", 0),
        ):
            result = get_dedupe_audience_count_v2(self.team, FILTERS, "email")

        assert (result.affected, result.total) == (3, 3)

    def test_dedupe_sampling_predicate_reaches_raw_person_prefilter(self):
        # Same guard as the person-count variant below, for the group-hash predicate.
        cleaned_filter = replace_proxy_properties(self.team, FILTERS)
        query = build_dedupe_count_query(self.team, cleaned_filter, sample_modulus=64)
        response = execute_hogql_query(query=query, team=self.team, settings=bounded_memory_settings())

        clickhouse_sql = response.clickhouse
        assert clickhouse_sql is not None
        assert "AS where_optimization" in clickhouse_sql
        assert "cityHash64" in clickhouse_sql.split("AS where_optimization", 1)[1]

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
