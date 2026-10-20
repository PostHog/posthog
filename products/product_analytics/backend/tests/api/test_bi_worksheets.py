from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import Team

from products.product_analytics.backend.models.insight import Insight


class TestBIWorksheetLists(APIBaseTest):
    @parameterized.expand(
        [
            ({"insight": "BI"}, ["Worksheet"]),
            ({"exclude_bi": "true"}, ["Trend"]),
            ({"exclude_bi": "false"}, ["Trend", "Worksheet"]),
        ]
    )
    def test_separates_worksheets_without_exposing_other_projects(
        self, filters: dict[str, str], names: list[str]
    ) -> None:
        query = {"kind": "BIVisualizationNode", "source": {"kind": "HogQLQuery", "query": "select 1"}}
        Insight.objects.create(team=self.team, name="Worksheet", saved=True, query=query)
        Insight.objects.create(team=self.team, name="Trend", saved=True)
        other_team = Team.objects.create(organization=self.organization)
        Insight.objects.create(team=other_team, name="Other project", saved=True, query=query)
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/", {"basic": "true", "saved": "true", **filters}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(item["name"] for item in response.json()["results"]), names)
