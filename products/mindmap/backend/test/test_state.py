from posthog.test.base import APIBaseTest

from rest_framework import status

from products.mindmap.backend.models import MindMapEdge, MindMapPostIt


class TestStateEndpoint(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.pk}/mindmap/state/"

    def test_empty_state(self) -> None:
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["postits"], [])
        self.assertEqual(body["edges"], [])
        self.assertTrue(body["version"])

    def test_returns_postits_and_edges(self) -> None:
        a = MindMapPostIt.objects.create(team=self.team, title="A")
        b = MindMapPostIt.objects.create(team=self.team, title="B")
        MindMapEdge.objects.create(team=self.team, source=a, target=b)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(len(body["postits"]), 2)
        self.assertEqual(body["edges"], [{"source": a.short_id, "target": b.short_id}])

    def test_304_when_unchanged(self) -> None:
        MindMapPostIt.objects.create(team=self.team, title="A")
        first = self.client.get(self._url())
        etag = first.headers["ETag"]
        second = self.client.get(self._url(), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(second.status_code, status.HTTP_304_NOT_MODIFIED)

    def test_version_changes_on_soft_delete(self) -> None:
        a = MindMapPostIt.objects.create(team=self.team, title="A")
        v1 = self.client.get(self._url()).json()["version"]
        a.deleted = True
        a.save()
        v2 = self.client.get(self._url()).json()["version"]
        self.assertNotEqual(v1, v2)

    def test_soft_deleted_postits_excluded(self) -> None:
        MindMapPostIt.objects.create(team=self.team, title="visible")
        MindMapPostIt.objects.create(team=self.team, title="hidden", deleted=True)
        response = self.client.get(self._url())
        titles = [p["title"] for p in response.json()["postits"]]
        self.assertEqual(titles, ["visible"])
