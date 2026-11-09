from posthog.test.base import APIBaseTest

from posthog.models import Team

from products.marketing_analytics.backend.models.recommendation_dismissal import RecommendationDismissal


class TestRecommendationDismissals(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/marketing_analytics_recommendation_dismissals/"

    def test_dismissing_twice_keeps_one_dismissal(self) -> None:
        body = {"rule": "brand_leak", "subject": "example shoes", "campaign": "Example campaign"}

        first = self.client.post(self.base, body)
        second = self.client.post(self.base, body)

        assert first.status_code == 201, first.json()
        assert second.status_code == 201, second.json()
        assert second.json()["id"] == first.json()["id"]
        listed = self.client.get(self.base).json()
        assert [(d["rule"], d["subject"], d["campaign"]) for d in listed] == [
            ("brand_leak", "example shoes", "Example campaign")
        ]
        assert listed[0]["dismissed_by"]["id"] == self.user.id

        other_campaign = self.client.post(self.base, {**body, "campaign": " Example campaign "})
        assert other_campaign.json()["id"] != first.json()["id"]
        assert other_campaign.json()["campaign"] == " Example campaign "

    def test_another_team_cannot_see_or_delete_a_dismissal(self) -> None:
        dismissal_id = self.client.post(self.base, {"rule": "keyword_gap", "subject": "example boots"}).json()["id"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_base = f"/api/projects/{other_team.pk}/marketing_analytics_recommendation_dismissals/"

        assert self.client.get(other_base).json() == []
        assert self.client.delete(f"{other_base}{dismissal_id}/").status_code == 404
        assert RecommendationDismissal.objects.for_team(self.team.pk).filter(id=dismissal_id).exists()

        assert self.client.delete(f"{self.base}{dismissal_id}/").status_code == 204
        assert self.client.get(self.base).json() == []
