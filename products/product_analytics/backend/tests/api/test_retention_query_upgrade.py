from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.schema import CachedRetentionQueryResponse, MeanRetentionCalculation, RetentionQuery


class TestRetentionQueryUpgrade(APIBaseTest):
    @patch("posthog.api.query.process_query_model")
    def test_query_endpoint_upgrades_before_running(self, mock_process_query):
        mock_process_query.return_value = CachedRetentionQueryResponse(
            cache_key="cache_123",
            is_cached=False,
            last_refresh="2023-10-16T12:00:00Z",
            next_allowed_client_refresh="2023-10-16T14:00:00Z",
            results=[],
            timezone="UTC",
        )

        self.client.post(
            f"/api/environments/{self.team.id}/query/",
            {
                "query": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {
                        "period": "Day",
                        "totalIntervals": 8,
                        "targetEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                        "returningEntity": {"id": "$pageview", "name": "$pageview", "type": "events"},
                        "retentionType": "retention_first_time",
                        "showMean": True,
                    },
                },
                "client_query_id": "5d92fb51-5088-45e8-91b2-843aef3d69bd",
            },
        ).json()

        mock_process_query.assert_called_once()
        updated_query = mock_process_query.call_args.args[1]
        assert isinstance(updated_query, RetentionQuery)
        assert updated_query.version == 2
        assert updated_query.retentionFilter.meanRetentionCalculation == MeanRetentionCalculation.SIMPLE

    def test_upgrade_endpoint_returns_the_migrated_query(self):
        query = {"kind": "RetentionQuery", "retentionFilter": {"period": "Day", "totalIntervals": 7, "showMean": True}}

        response = self.client.post(f"/api/environments/{self.team.id}/query/upgrade/", {"query": query})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "query": {
                    "kind": "RetentionQuery",
                    "retentionFilter": {"meanRetentionCalculation": "simple", "period": "Day", "totalIntervals": 7},
                    "version": 2,
                }
            },
        )
