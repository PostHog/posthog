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

    def test_can_create_annotation_and_sets_created_by(self):
        res = self.client.post(
            f"/api/environments/{self.team.id}/llm_analytics/annotations/",
            data={
                "target_type": "trace",
                "target_id": "trace-post",
                "content": "created via api",
                "rating": 4,
                "data": {"source": "test"},
            },
            format="json",
        )
        self.assertEqual(res.status_code, 201)

        payload = res.json()

        # created_by is serialized (basic user) and should match the authed user
        self.assertEqual(payload["created_by"]["id"], self.user.id)

        obj = LLMAnalyticsAnnotation.objects.get(team_id=self.team.id, target_id="trace-post")
        self.assertEqual(obj.created_by_id, self.user.id)
