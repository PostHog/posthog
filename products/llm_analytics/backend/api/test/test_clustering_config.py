from posthog.test.base import APIBaseTest

from rest_framework import status

from products.llm_analytics.backend.models.clustering_config import ClusteringConfig


class TestClusteringConfigViewSet(APIBaseTest):
    def test_unauthenticated_user_cannot_access_config(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_can_get_clustering_config(self):
        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertIn("event_filters", response.data)
        self.assertIn("created_at", response.data)
        self.assertIn("updated_at", response.data)
        self.assertEqual(response.data["event_filters"], [])

    def test_get_creates_config_if_missing(self):
        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 0)

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(ClusteringConfig.objects.filter(team=self.team).count(), 1)

    def test_get_returns_existing_config(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 1)
        self.assertEqual(response.data["event_filters"][0]["key"], "ai_product")

    def test_can_set_event_filters(self):
        filters = [{"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"}]

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], filters)

        config = ClusteringConfig.objects.get(team=self.team)
        self.assertEqual(config.event_filters, filters)

    def test_can_clear_event_filters(self):
        ClusteringConfig.objects.create(
            team=self.team,
            event_filters=[{"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"}],
        )

        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["event_filters"], [])

    def test_set_event_filters_requires_event_filters_field(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("event_filters", response.data["detail"].lower())

    def test_set_event_filters_rejects_non_list(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": "not a list"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("list", response.data["detail"].lower())

    def test_set_event_filters_persists_across_requests(self):
        filters = [
            {"key": "ai_product", "value": "posthog_ai", "operator": "exact", "type": "event"},
            {"key": "$ai_model", "value": "gpt-4", "operator": "exact", "type": "event"},
        ]

        self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/clustering_config/set_event_filters/",
            {"event_filters": filters},
            format="json",
        )

        response = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/clustering_config/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["event_filters"]), 2)
