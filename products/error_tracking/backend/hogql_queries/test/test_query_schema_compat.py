from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError

from posthog.schema import ErrorTrackingQuery, QueryRequest


class TestErrorTrackingQuerySchemaCompat(SimpleTestCase):
    # Older frontend bundles still send the deprecated query-path flags. The schema must
    # keep accepting them until no clients send them anymore — removing them breaks every
    # stale tab with a hard 400 during deploys (extra="forbid").
    @parameterized.expand([("useQueryV2", False), ("useQueryV3", True)])
    def test_accepts_deprecated_query_path_flags(self, flag: str, value: bool) -> None:
        request = QueryRequest.model_validate(
            {
                "query": {
                    "kind": "ErrorTrackingQuery",
                    "orderBy": "last_seen",
                    "dateRange": {"date_from": "-7d"},
                    "volumeResolution": 20,
                    flag: value,
                }
            }
        )
        assert getattr(request.query, flag) == value

    @parameterized.expand([0, 200])
    def test_accepts_volume_resolution_boundaries(self, resolution: int) -> None:
        request = QueryRequest.model_validate(
            {
                "query": {
                    "kind": "ErrorTrackingQuery",
                    "orderBy": "last_seen",
                    "dateRange": {"date_from": "-7d"},
                    "volumeResolution": resolution,
                }
            }
        )
        assert isinstance(request.query, ErrorTrackingQuery)
        assert request.query.volumeResolution == resolution

    @parameterized.expand([(-1, "greater_than_equal"), (201, "less_than_equal")])
    def test_rejects_invalid_volume_resolution(self, resolution: int, error_type: str) -> None:
        with self.assertRaises(ValidationError) as raised:
            QueryRequest.model_validate(
                {
                    "query": {
                        "kind": "ErrorTrackingQuery",
                        "orderBy": "last_seen",
                        "dateRange": {"date_from": "-7d"},
                        "volumeResolution": resolution,
                    }
                }
            )
        assert raised.exception.errors()[0]["loc"] == ("query", "ErrorTrackingQuery", "volumeResolution")
        assert raised.exception.errors()[0]["type"] == error_type
