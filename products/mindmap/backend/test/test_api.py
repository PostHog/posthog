from posthog.test.base import APIBaseTest

from rest_framework import status

from products.mindmap.backend.models import MindMapPostIt


class TestPostItAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.pk}/mindmap_postits/{suffix}"

    def test_create_postit(self) -> None:
        response = self.client.post(self._url(), {"title": "Onboarding"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        data = response.json()
        self.assertEqual(data["title"], "Onboarding")
        self.assertEqual(data["color"], "yellow")
        self.assertTrue(data["short_id"])

    def test_list_excludes_deleted(self) -> None:
        a = MindMapPostIt.objects.create(team=self.team, title="A")
        MindMapPostIt.objects.create(team=self.team, title="B", deleted=True)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [p["short_id"] for p in response.json()["results"]]
        self.assertEqual(ids, [a.short_id])

    def test_partial_update(self) -> None:
        postit = MindMapPostIt.objects.create(team=self.team, title="A")
        response = self.client.patch(self._url(postit.short_id + "/"), {"body": "hi", "color": "blue"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["body"], "hi")
        self.assertEqual(response.json()["color"], "blue")

    def test_destroy_soft_deletes(self) -> None:
        postit = MindMapPostIt.objects.create(team=self.team, title="A")
        response = self.client.delete(self._url(postit.short_id + "/"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        postit.refresh_from_db()
        self.assertTrue(postit.deleted)

    def test_bulk_position(self) -> None:
        a = MindMapPostIt.objects.create(team=self.team, title="A")
        b = MindMapPostIt.objects.create(team=self.team, title="B")
        response = self.client.post(
            self._url("bulk_position/"),
            {
                "updates": [
                    {"short_id": a.short_id, "position_x": 10.0, "position_y": 20.0},
                    {"short_id": b.short_id, "position_x": 5.0, "position_y": -5.0},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(response.json()["updated"], 2)
        a.refresh_from_db()
        self.assertEqual((a.position_x, a.position_y), (10.0, 20.0))

    def test_team_isolation(self) -> None:
        other_team = self.organization.teams.create(name="other")
        other_postit = MindMapPostIt.objects.create(team=other_team, title="hidden")
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [p["short_id"] for p in response.json()["results"]]
        self.assertNotIn(other_postit.short_id, ids)
