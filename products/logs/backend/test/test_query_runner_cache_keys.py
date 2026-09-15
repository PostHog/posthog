from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import DateRange, FilterLogicalOperator, LogsQuery, PropertyGroupFilter

from products.logs.backend.count_ranges_query_runner import CountRangesQueryRunner
from products.logs.backend.log_facet_values_query_runner import LogFacetValuesQueryRunner
from products.logs.backend.services_query_runner import ServicesQueryRunner


class TestRunnerArgumentsReachTheCacheKey(BaseTest):
    @parameterized.expand(
        [
            ("services_search", ServicesQueryRunner, {"service_name_search": "api"}, {"service_name_search": "web"}),
            (
                "facet_field",
                LogFacetValuesQueryRunner,
                {"facet_field": "service_name"},
                {"facet_field": "severity_text"},
            ),
            (
                "facet_attribute_type",
                LogFacetValuesQueryRunner,
                {"facet_resource_attribute": "k8s.pod.name"},
                {"facet_attribute": "k8s.pod.name"},
            ),
            (
                "facet_search",
                LogFacetValuesQueryRunner,
                {"facet_field": "service_name", "facet_search": "kafka"},
                {"facet_field": "service_name"},
            ),
            ("count_ranges_buckets", CountRangesQueryRunner, {"target_buckets": 10}, {"target_buckets": 20}),
        ]
    )
    def test_different_runner_arguments_give_different_cache_keys(self, _name, runner_class, first, second):
        query = LogsQuery(
            dateRange=DateRange(date_from="-1h"),
            serviceNames=[],
            severityLevels=[],
            filterGroup=PropertyGroupFilter(type=FilterLogicalOperator.AND_, values=[]),
        )
        first_key = runner_class(query=query, team=self.team, **first).get_cache_key()
        second_key = runner_class(query=query, team=self.team, **second).get_cache_key()
        assert first_key != second_key
