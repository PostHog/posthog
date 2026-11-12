from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.release.backend.models import Release
from products.workflows.backend.facade.testing import create_workflow_for_test

FLAG_PATCH = "products.release.backend.facade.api.releases_enabled"


class TestReleaseAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        flag = patch(FLAG_PATCH, return_value=True)
        flag.start()
        self.addCleanup(flag.stop)

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
        [
            ("existing", "existing", status.HTTP_201_CREATED),
            ("unknown", "unknown", status.HTTP_400_BAD_REQUEST),
            ("hidden_from_the_caller", "hidden", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_linked_flags_must_exist_and_be_visible(self, _name: str, flag: str, expected: int) -> None:
        flag_id = 999999
        if flag != "unknown":
            flag_id = self.client.post(
                f"/api/projects/{self.team.id}/feature_flags/", {"key": "dark-mode"}, format="json"
            ).json()["id"]
        if flag == "hidden":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
                {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
            ]
            self.organization.save()
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
            restricted = self.client.put(
                f"/api/projects/{self.team.id}/feature_flags/{flag_id}/access_controls",
                {"access_level": "none"},
                format="json",
            )
            assert restricted.status_code == status.HTTP_200_OK, restricted.json()
            self.client.force_login(self._create_user("member@example.com"))

        response = self.client.post(self._url(), {"name": "Dark mode", "feature_flag_ids": [flag_id]}, format="json")

        assert response.status_code == expected, response.json()

    @parameterized.expand([("active", False), ("soft_deleted", True)])
    def test_hidden_flags_are_omitted_and_kept_while_deleted_flags_still_show(
        self, _name: str, hidden_flag_deleted: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        visible_id, hidden_id, deleted_id = (
            self.client.post(f"/api/projects/{self.team.id}/feature_flags/", {"key": key}, format="json").json()["id"]
            for key in ("visible", "hidden", "deleted")
        )
        release_id = self.client.post(
            self._url(), {"name": "Dark mode", "feature_flag_ids": [visible_id, hidden_id, deleted_id]}, format="json"
        ).json()["id"]
        self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{deleted_id}/", {"deleted": True}, format="json")
        self.client.put(
            f"/api/projects/{self.team.id}/feature_flags/{hidden_id}/access_controls",
            {"access_level": "none"},
            format="json",
        )
        if hidden_flag_deleted:
            deleted = self.client.patch(
                f"/api/projects/{self.team.id}/feature_flags/{hidden_id}/", {"deleted": True}, format="json"
            )
            assert deleted.status_code == status.HTTP_200_OK, deleted.json()
        admin = self.user
        self.client.force_login(self._create_user("member@example.com"))

        member_view = self.client.get(self._url()).json()["results"][0]
        listed = member_view["feature_flag_ids"]
        guessed_linked = self.client.patch(
            self._url(f"{release_id}/"), {"feature_flag_ids": [visible_id, hidden_id]}, format="json"
        )
        guessed_unknown = self.client.patch(
            self._url(f"{release_id}/"), {"feature_flag_ids": [visible_id, 999999]}, format="json"
        )
        self.client.patch(self._url(f"{release_id}/"), {"feature_flag_ids": []}, format="json")
        self.client.force_login(admin)
        kept = self.client.get(self._url()).json()["results"][0]["feature_flag_ids"]

        assert listed == [visible_id, deleted_id]
        assert member_view["has_hidden_flags"] is True
        assert guessed_linked.status_code == guessed_unknown.status_code == status.HTTP_400_BAD_REQUEST
        assert kept == [hidden_id]

    @parameterized.expand(
        [("list", "get", ""), ("create", "post", ""), ("update", "patch", "00000000-0000-0000-0000-000000000000/")]
    )
    def test_every_action_is_closed_without_the_flag(self, _name: str, method: str, suffix: str) -> None:
        with patch(FLAG_PATCH, return_value=False):
            response = getattr(self.client, method)(self._url(suffix), {"name": "Dark mode"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def _restrict_as_admin(self, resource_path: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        restricted = self.client.put(
            f"/api/projects/{self.team.id}/{resource_path}/access_controls", {"access_level": "none"}, format="json"
        )
        assert restricted.status_code == status.HTTP_200_OK, restricted.json()

    @parameterized.expand(
        [
            ("existing", "existing", status.HTTP_201_CREATED),
            ("unknown", "unknown", status.HTTP_400_BAD_REQUEST),
            ("hidden_from_the_caller", "hidden", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_linked_broadcasts_must_exist_and_be_visible(self, _name: str, broadcast: str, expected: int) -> None:
        broadcast_id = "00000000-0000-0000-0000-000000000001"
        if broadcast != "unknown":
            broadcast_id = create_workflow_for_test(team_id=self.team.id, name="Launch email").id
        if broadcast == "hidden":
            self._restrict_as_admin(f"hog_flows/{broadcast_id}")
            self.client.force_login(self._create_user("member@example.com"))

        response = self.client.post(self._url(), {"name": "Dark mode", "broadcast_ids": [broadcast_id]}, format="json")

        assert response.status_code == expected, response.json()
        if expected == status.HTTP_201_CREATED:
            assert response.json()["broadcast_ids"] == [broadcast_id]

    def test_hidden_broadcasts_are_omitted_and_kept_on_update(self) -> None:
        visible_id, hidden_id = (
            create_workflow_for_test(team_id=self.team.id, name=name).id for name in ("Launch email", "Beta email")
        )
        release_id = self.client.post(
            self._url(), {"name": "Dark mode", "broadcast_ids": [visible_id, hidden_id]}, format="json"
        ).json()["id"]
        self._restrict_as_admin(f"hog_flows/{hidden_id}")
        self.client.force_login(self._create_user("member@example.com"))

        member_view = self.client.get(self._url()).json()["results"][0]
        self.client.patch(self._url(f"{release_id}/"), {"broadcast_ids": []}, format="json")
        stored = Release.objects.unscoped().get(id=release_id).broadcast_ids

        assert member_view["broadcast_ids"] == [visible_id]
        assert [broadcast["name"] for broadcast in member_view["broadcasts"]] == ["Launch email"]
        assert [str(broadcast_id) for broadcast_id in stored] == [hidden_id]

    @parameterized.expand(
        [
            ("flags_only", ["feature_flag:read"], False),
            ("flags_and_workflows", ["feature_flag:read", "hog_flow:read"], True),
            ("full_access", ["*"], True),
        ]
    )
    def test_broadcasts_follow_the_workflow_scope(self, _name: str, scopes: list[str], shown: bool) -> None:
        broadcast_id = create_workflow_for_test(team_id=self.team.id, name="Launch email").id
        self.client.post(self._url(), {"name": "Dark mode", "broadcast_ids": [broadcast_id]}, format="json")
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        release = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {token}").json()["results"][0]

        assert release["broadcast_ids"] == ([str(broadcast_id)] if shown else [])
        assert [broadcast["name"] for broadcast in release["broadcasts"]] == (["Launch email"] if shown else [])

    def test_broadcast_search_returns_matching_broadcasts(self) -> None:
        for name in ("Launch email", "Weekly digest"):
            create_workflow_for_test(
                team_id=self.team.id,
                name=name,
                trigger={"type": "batch"},
                actions=[
                    {"id": "trigger", "name": "trigger", "type": "trigger", "config": {"type": "batch"}},
                    {"id": "email", "name": "email", "type": "function_email", "config": {}},
                ],
            )

        response = self.client.get(self._url("broadcast_search/?search=launch"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [option["name"] for option in response.json()] == ["Launch email"]

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
