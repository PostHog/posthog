from typing import Any

from parameterized import parameterized

from posthog.test.clickhouse_free import ClickhouseFreeSimpleTestCase

from products.experiments.backend.presentation.serializers import ExperimentSessionBucketRequestSerializer


class TestExperimentSessionBucketRequestValidation(ClickhouseFreeSimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_bucket", {"bucket": "helped"}, "bucket"),
            ("dropoff_without_metric", {"bucket": "funnel_dropoff"}, "metric_uuids"),
            ("dropoff_with_two_metrics", {"bucket": "funnel_dropoff", "metric_uuids": ["a", "b"]}, "metric_uuids"),
            ("limit_over_cap", {"bucket": "fired_any", "limit": 500}, "limit"),
        ]
    )
    def test_rejects_invalid_requests(self, _name: str, payload: dict[str, Any], expected_field: str) -> None:
        serializer = ExperimentSessionBucketRequestSerializer(data=payload)

        assert not serializer.is_valid()
        assert expected_field in serializer.errors
