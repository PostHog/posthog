from posthog.test.base import APIBaseTest

from posthog.models import Team

from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution


class TestRecommendationResolutions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/marketing_analytics_recommendation_resolutions/"

    def test_resolving_again_replaces_the_resolution(self) -> None:
        body = {
            "rule": "spend_without_conversions",
            "source_type": "google_ads",
            "customer_id": "1234567890",
            "campaign_id": "",
            "subject": "example shoes",
            "resolution": "dismissed",
            "snapshot": {"action": "Add as a negative keyword", "impact": 120.0, "currency": "USD"},
        }

        first = self.client.post(self.base, body, format="json")
        second = self.client.post(
            self.base, {**body, "resolution": "applied", "snapshot": {"action": "Pause it"}}, format="json"
        )

        assert first.status_code == 201, first.json()
        assert second.status_code == 201, second.json()
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["created_at"] == first.json()["created_at"]
        assert second.json()["resolved_at"] > first.json()["resolved_at"]
        stored = RecommendationResolution.objects.for_team(self.team.pk).get(id=first.json()["id"])
        assert (stored.resolution, stored.snapshot, stored.resolved_by_id) == (
            "applied",
            {"action": "Pause it", "impact": None, "currency": None},
            self.user.id,
        )

        other_account = self.client.post(self.base, {**body, "customer_id": "9876543210"}, format="json")
        assert other_account.json()["id"] != first.json()["id"]
        edge_spaces = self.client.post(self.base, {**body, "subject": " example shoes "}, format="json")
        assert edge_spaces.json()["subject"] == " example shoes "

    def test_another_team_cannot_delete_a_resolution(self) -> None:
        resolution_id = self.client.post(
            self.base, {"rule": "keyword_gap", "subject": "example boots", "resolution": "dismissed"}
        ).json()["id"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_base = f"/api/projects/{other_team.pk}/marketing_analytics_recommendation_resolutions/"

        assert self.client.delete(f"{other_base}{resolution_id}/").status_code == 404
        assert RecommendationResolution.objects.for_team(self.team.pk).filter(id=resolution_id).exists()

        assert self.client.delete(f"{self.base}{resolution_id}/").status_code == 204
        assert not RecommendationResolution.objects.for_team(self.team.pk).exists()
