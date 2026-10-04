from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import QueryRequest


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
