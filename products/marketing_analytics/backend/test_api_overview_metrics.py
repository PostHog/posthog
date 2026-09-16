from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.api.team import TeamMarketingAnalyticsConfigSerializer
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team_marketing_analytics_config import DEFAULT_OVERVIEW_METRICS, TeamMarketingAnalyticsConfig


class TestOverviewMetricsValidation(SimpleTestCase):
    @parameterized.expand(
        [
            ("unknown_key", ["visitors", "bogus"]),
            ("duplicate_key", ["visitors", "visitors"]),
            ("not_a_list", "visitors"),
            ("non_string_member", ["visitors", 7]),
        ]
    )
    def test_rejects_invalid_overview_metrics(self, _name: str, value: object) -> None:
        serializer = TeamMarketingAnalyticsConfigSerializer(data={"overview_metrics": value}, partial=True)

        assert not serializer.is_valid()
        assert "overview_metrics" in serializer.errors

    def test_accepts_a_reordered_subset(self) -> None:
        serializer = TeamMarketingAnalyticsConfigSerializer(
            data={"overview_metrics": ["revenue", "visitors"]}, partial=True
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["overview_metrics"] == ["revenue", "visitors"]

    @parameterized.expand([("unset", []), ("explicitly_empty", [])])
    def test_empty_reads_back_as_the_default_set(self, _name: str, stored: list[str]) -> None:
        config = TeamMarketingAnalyticsConfig(_overview_metrics=stored)

        assert config.overview_metrics == DEFAULT_OVERVIEW_METRICS

    def test_configured_order_is_preserved(self) -> None:
        config = TeamMarketingAnalyticsConfig(_overview_metrics=["revenue", "visitors"])

        assert config.overview_metrics == ["revenue", "visitors"]


class TestOverviewMetricsAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The field is project-admin gated, same as the rest of the marketing settings PATCH path.
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    # Wiring guards: the matrix above proves the validation, these prove the viewset runs it.
    def test_rejects_unknown_metric_without_persisting(self) -> None:
        response = self.client.patch(
            f"/api/environments/{self.team.id}/",
            {"marketing_analytics_config": {"overview_metrics": ["visitors", "bogus"]}},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert TeamMarketingAnalyticsConfig.objects.get(team=self.team)._overview_metrics == []

    def test_empty_list_restores_the_default(self) -> None:
        url = f"/api/environments/{self.team.id}/"

        self.client.patch(url, {"marketing_analytics_config": {"overview_metrics": ["revenue"]}}, format="json")
        assert self.client.get(url).json()["marketing_analytics_config"]["overview_metrics"] == ["revenue"]

        self.client.patch(url, {"marketing_analytics_config": {"overview_metrics": []}}, format="json")

        assert self.client.get(url).json()["marketing_analytics_config"]["overview_metrics"] == DEFAULT_OVERVIEW_METRICS
        assert TeamMarketingAnalyticsConfig.objects.get(team=self.team)._overview_metrics == []
