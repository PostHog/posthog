from posthog.test.base import APIBaseTest

from posthog.models.team import Team

from products.llm_analytics.backend.models.annotations import LLMAnalyticsAnnotation


class TestLLMAnalyticsAnnotationsAPI(APIBaseTest):
    def test_list_is_scoped_to_team(self):
        # Create an annotation in this team
        LLMAnalyticsAnnotation.objects.create(
            team_id=self.team.id,
            organization_id=self.team.organization_id,
            target_type="trace",
            target_id="trace-1",
            content="hello",
            rating=5,
            data={"source": "test"},
        )

        # Create an annotation for another team (same org)
        other_team = Team.objects.create(name="Other Team", organization=self.organization)
        LLMAnalyticsAnnotation.objects.create(
            team_id=other_team.id,
            organization_id=other_team.organization_id,
            target_type="trace",
            target_id="trace-2",
            content="should not show up",
            rating=1,
            data={"source": "test"},
        )

        res = self.client.get(f"/api/environments/{self.team.id}/llm_analytics/annotations/")
        self.assertEqual(res.status_code, 200)

        payload = res.json()
        ids = [r["target_id"] for r in payload["results"]]
        self.assertIn("trace-1", ids)
        self.assertNotIn("trace-2", ids)
