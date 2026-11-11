from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, User


class TestReleaseAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/releases/{suffix}"

    @parameterized.expand([("member", True, status.HTTP_201_CREATED), ("outsider", False, status.HTTP_400_BAD_REQUEST)])
    def test_owner_must_belong_to_the_organization(self, _name: str, is_member: bool, expected: int) -> None:
        if is_member:
            owner_id = self.user.id
        else:
            other_organization = Organization.objects.create(name="Other")
            owner_id = User.objects.create_and_join(other_organization, "outsider@example.com", None).id

        response = self.client.post(self._url(), {"name": "Dark mode", "owner_id": owner_id}, format="json")

        assert response.status_code == expected, response.json()

    @parameterized.expand(
        [("existing", True, status.HTTP_201_CREATED), ("unknown", False, status.HTTP_400_BAD_REQUEST)]
    )
    def test_linked_flags_must_exist_in_the_project(self, _name: str, exists: bool, expected: int) -> None:
        if exists:
            flag_id = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/", {"key": "dark-mode"}, format="json"
            ).json()["id"]
        else:
            flag_id = 999999

        response = self.client.post(self._url(), {"name": "Dark mode", "feature_flag_ids": [flag_id]}, format="json")

        assert response.status_code == expected, response.json()

    def test_update_of_a_missing_release_returns_404(self) -> None:
        response = self.client.patch(
            self._url("00000000-0000-0000-0000-000000000000/"), {"name": "Renamed"}, format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_list_returns_a_page_with_a_link_to_the_next_one(self) -> None:
        for name in ("First", "Second"):
            self.client.post(self._url(), {"name": name}, format="json")

        response = self.client.get(self._url("?limit=1"))

        body = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert body["count"] == 2
        assert [release["name"] for release in body["results"]] == ["First"]
        assert body["next"] is not None
