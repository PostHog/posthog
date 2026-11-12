from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.schema import MarketingAnalyticsRecommendationIdentity

from posthog.models import Team
from posthog.models.activity_logging.activity_log import ActivityLog

from products.marketing_analytics.backend.hogql_queries.recommendation_identity import RecommendationKey
from products.marketing_analytics.backend.models.recommendation_resolution import RecommendationResolution

IDENTITY = {
    "rule": "spend_without_conversions",
    "source_type": "google_ads",
    "customer_id": "1234567890",
    "campaign_id": "",
    "subject": "example shoes",
}


class TestRecommendationResolutions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/marketing_analytics_recommendation_resolutions/"

    def _resolve(self, identity: dict[str, str], resolution: str = "dismissed", base: str | None = None):
        return self.client.post(base or self.base, {"identity": identity, "resolution": resolution}, format="json")

    def test_resolving_again_replaces_the_resolution(self) -> None:
        first = self._resolve(IDENTITY)
        second = self._resolve(IDENTITY, "applied")

        assert first.status_code == 201, first.json()
        assert second.status_code == 200, second.json()
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["created_at"] == first.json()["created_at"]
        assert second.json()["resolved_at"] > first.json()["resolved_at"]
        assert (second.json()["resolution"], second.json()["resolved_by"]["id"]) == ("applied", self.user.id)
        assert [
            (log.activity, log.user_id, [change["field"] for change in (log.detail or {}).get("changes") or []])
            for log in ActivityLog.objects.filter(scope="RecommendationResolution").order_by("created_at")
        ] == [("created", self.user.id, []), ("updated", self.user.id, ["resolution"])]

        other_account = self._resolve({**IDENTITY, "customer_id": "9876543210"})
        assert other_account.status_code == 201
        assert other_account.json()["id"] != first.json()["id"]
        edge_spaces = self._resolve({**IDENTITY, "subject": " example shoes "})
        assert edge_spaces.json()["identity"]["subject"] == " example shoes "
        long_multibyte = self._resolve({**IDENTITY, "subject": "靴" * 1500})
        assert long_multibyte.status_code == 201, long_multibyte.json()
        long_log = ActivityLog.objects.get(scope="RecommendationResolution", item_id=long_multibyte.json()["id"])
        assert (long_log.detail or {})["name"] == "靴" * 199 + "…"
        assert self._resolve({**IDENTITY, "subject": "靴" * 1500}).status_code == 200

    @parameterized.expand(
        [
            ("unknown_rule", {"rule": "pause_everything"}),
            ("account_agnostic_rule_with_an_account", {"rule": "keyword_gap"}),
            ("search_term_rule_with_a_campaign", {"campaign_id": "c1"}),
            ("search_term_rule_without_a_term", {"subject": ""}),
            ("campaign_rule_without_a_campaign", {"rule": "policy_limited", "subject": ""}),
            ("campaign_rule_with_a_subject", {"rule": "policy_limited", "campaign_id": "c1"}),
        ]
    )
    def test_rejects_an_identity_the_rule_cannot_produce(self, _name: str, overrides: dict[str, str]) -> None:
        response = self._resolve({**IDENTITY, **overrides})

        assert response.status_code == 400, response.json()
        assert not RecommendationResolution.objects.for_team(self.team.pk).exists()

    def test_another_team_cannot_list_or_delete_a_resolution(self) -> None:
        resolution_id = self._resolve(IDENTITY).json()["id"]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_base = f"/api/projects/{other_team.pk}/marketing_analytics_recommendation_resolutions/"

        assert self.client.get(other_base).json()["results"] == []
        assert [(row["id"], row["key"]) for row in self.client.get(self.base).json()["results"]] == [
            (
                resolution_id,
                RecommendationKey.from_identity(MarketingAnalyticsRecommendationIdentity(**IDENTITY)).encoded,
            )
        ]
        assert self.client.delete(f"{other_base}{resolution_id}/").status_code == 404
        assert RecommendationResolution.objects.for_team(self.team.pk).filter(id=resolution_id).exists()

        assert self.client.delete(f"{self.base}{resolution_id}/").status_code == 204
        assert not RecommendationResolution.objects.for_team(self.team.pk).exists()
        assert ActivityLog.objects.filter(scope="RecommendationResolution", activity="deleted").count() == 1
