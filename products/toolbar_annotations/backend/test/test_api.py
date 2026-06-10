from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.team.team import Team

from products.toolbar_annotations.backend.models import ToolbarAnnotation

VALID_PAYLOAD = {
    "comment": "This label needs less space",
    "url": "https://app.example.com/dashboard/42",
    "host": "app.example.com",
    "pathname": "/dashboard/42",
    "selector": ".header > .title",
    "element_text": "Overview",
    "element_context": {"inferred": {"text": "Overview"}},
    "viewport": {"width": 1440, "height": 900},
}


class TestToolbarAnnotationsAPI(APIBaseTest):
    def _create(self, **overrides) -> dict:
        response = self.client.post(
            f"/api/projects/{self.team.id}/toolbar_annotations/", data={**VALID_PAYLOAD, **overrides}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.json())
        return response.json()

    def test_create_sets_team_and_defaults(self):
        created = self._create()
        self.assertEqual(created["comment"], VALID_PAYLOAD["comment"])
        self.assertEqual(created["host"], "app.example.com")
        self.assertEqual(created["annotation_status"], "pending")
        self.assertEqual(created["created_by"]["id"], self.user.pk)

        annotation = ToolbarAnnotation.objects.for_team(self.team.id).get(id=created["id"])
        self.assertEqual(annotation.team_id, self.team.id)

    def test_list_filters_by_status_and_host(self):
        self._create()
        resolved = self._create(comment="already done")
        self.client.patch(
            f"/api/projects/{self.team.id}/toolbar_annotations/{resolved['id']}/",
            data={"annotation_status": "resolved"},
        )
        self._create(host="other.example.com")

        pending = self.client.get(
            f"/api/projects/{self.team.id}/toolbar_annotations/?annotation_status=pending"
        ).json()["results"]
        self.assertEqual(len(pending), 2)

        by_host = self.client.get(f"/api/projects/{self.team.id}/toolbar_annotations/?host=other.example.com").json()[
            "results"
        ]
        self.assertEqual(len(by_host), 1)
        self.assertEqual(by_host[0]["host"], "other.example.com")

    def test_resolve_with_note(self):
        created = self._create()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/toolbar_annotations/{created['id']}/",
            data={"annotation_status": "resolved", "resolution": "Tightened the label spacing"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["annotation_status"], "resolved")
        self.assertEqual(response.json()["resolution"], "Tightened the label spacing")

    def test_create_ignores_status_and_resolution(self):
        # A write-scoped toolbar token must not be able to forge a pre-resolved annotation.
        created = self._create(annotation_status="resolved", resolution="forged")
        self.assertEqual(created["annotation_status"], "pending")
        self.assertIsNone(created["resolution"])

    def test_list_rejects_invalid_status_filter(self):
        self._create()
        response = self.client.get(f"/api/projects/{self.team.id}/toolbar_annotations/?annotation_status=Resolved")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("comment", 5000),
            ("url", 2048),
            ("host", 255),
            ("pathname", 2048),
            ("selector", 4096),
            ("element_text", 2048),
            ("element_chain", 20000),
        ]
    )
    def test_create_rejects_oversized_field(self, field: str, limit: int):
        response = self.client.post(
            f"/api/projects/{self.team.id}/toolbar_annotations/",
            data={**VALID_PAYLOAD, field: "x" * (limit + 1)},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.json())

    def test_team_isolation(self):
        created = self._create()
        other_team = Team.objects.create(organization=self.organization, name="Other")

        in_other = self.client.get(f"/api/projects/{other_team.id}/toolbar_annotations/").json()["results"]
        self.assertEqual(in_other, [])

        detail = self.client.get(f"/api/projects/{other_team.id}/toolbar_annotations/{created['id']}/")
        self.assertEqual(detail.status_code, status.HTTP_404_NOT_FOUND)
