from posthog.test.base import APIBaseTest


class TestClusteringSettings(APIBaseTest):
    def test_clustering_settings_default(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_settings/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"trace_filters": []})

    def test_clustering_settings_update(self):
        payload = {
            "trace_filters": [
                {
                    "key": "ai_product",
                    "value": "posthog_ai",
                    "operator": "exact",
                    "type": "event",
                }
            ]
        }

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_settings/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)

        self.team.refresh_from_db()
        self.assertEqual(self.team.extra_settings.get("llm_analytics_trace_filters"), payload["trace_filters"])
