from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.release.backend.facade import api
from products.release.backend.facade.contracts import ImportFlag
from products.release.backend.models import Release, ReleaseImportState
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
        [
            ("list", "get", ""),
            ("create", "post", ""),
            ("update", "patch", "00000000-0000-0000-0000-000000000000/"),
            ("import_all", "post", "import_all/"),
        ]
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

    @parameterized.expand([("generated_name", False, "Release of a restricted flag"), ("renamed", True, "Checkout")])
    def test_generated_names_follow_the_flag_access(self, _name: str, renamed: bool, expected: str) -> None:
        flag_id = self._flag("secret-launch")
        self.client.post(self._url("import_all/"))
        release_id = self.client.get(self._url()).json()["results"][0]["id"]
        if renamed:
            self.client.patch(self._url(f"{release_id}/"), {"name": "Checkout"}, format="json")
        self._restrict_as_admin(f"feature_flags/{flag_id}")
        self.client.force_login(self._create_user("member@example.com"))

        assert self.client.get(self._url()).json()["results"][0]["name"] == expected

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

    def _flag(self, key: str, **extra) -> int:
        response = self.client.post(
            f"/api/projects/{self.team.id}/feature_flags/", {"key": key, **extra}, format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def test_import_all_creates_releases_only_for_active_unlinked_flags(self) -> None:
        linked = self._flag("linked-flag")
        self._flag("inactive-flag", active=False)
        self._flag("remote-config", is_remote_configuration=True)
        archived = self._flag("archived-flag")
        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{archived}/",
            {"active": False, "archived": True},
            format="json",
        )
        experiment = self.client.post(
            f"/api/projects/{self.team.id}/experiments/",
            {"name": "Pricing test", "feature_flag_key": "pricing-test"},
            format="json",
        )
        assert experiment.status_code == status.HTTP_201_CREATED, experiment.json()
        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{experiment.json()['feature_flag']['id']}/",
            {"active": True},
            format="json",
        )
        self._flag("quiet-theme")
        self.client.post(self._url(), {"name": "Linked", "feature_flag_ids": [linked]}, format="json")

        first = self.client.post(self._url("import_all/"))
        second = self.client.post(self._url("import_all/"))

        assert first.status_code == status.HTTP_201_CREATED, first.json()
        assert first.json()["created_count"] == 2
        assert second.json()["created_count"] == 0
        assert sorted(release["name"] for release in self.client.get(self._url()).json()["results"]) == [
            "Linked",
            "Pricing test",
            "Quiet theme",
        ]

    def test_import_all_covers_flags_the_caller_cannot_see(self) -> None:
        flag_id = self._flag("secret-launch")
        self._restrict_as_admin(f"feature_flags/{flag_id}")
        self.client.force_login(self._create_user("member@example.com"))

        created = self.client.post(self._url("import_all/")).json()["created_count"]

        assert created == 1
        assert [release["name"] for release in self.client.get(self._url()).json()["results"]] == [
            "Release of a restricted flag"
        ]

    def test_import_all_retries_an_import_that_never_completed(self) -> None:
        self._flag("quiet-theme")
        ReleaseImportState.objects.unscoped().create(team_id=self.team.id)

        created = self.client.post(self._url("import_all/")).json()["created_count"]

        assert created == 1

    def test_import_all_runs_once_per_project_and_writes_to_the_root_team(self) -> None:
        flag_id = self._flag("quiet-theme")
        environment = Team.objects.create(
            organization=self.organization, project=self.project, parent_team=self.team, name="env"
        )

        created = api.import_all(
            environment.id,
            lambda: [ImportFlag(id=flag_id, key="quiet-theme")],
        )
        release_id = self.client.get(self._url()).json()["results"][0]["id"]
        self.client.delete(self._url(f"{release_id}/"))
        again = self.client.post(self._url("import_all/")).json()["created_count"]

        assert (created, again) == (1, 0)
        assert self.client.get(self._url()).json()["count"] == 0

    @parameterized.expand(
        [
            ("import_all", "post", "feature_flag:write", status.HTTP_201_CREATED),
            ("import_all", "post", "feature_flag:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_import_actions_follow_feature_flag_scopes(
        self, action: str, method: str, scope: str, expected: int
    ) -> None:
        self._flag("checkout-v2")
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(token), scopes=[scope])
        self.client.logout()

        response = getattr(self.client, method)(
            self._url(f"{action}/"),
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        assert response.status_code == expected, response.json()

    def test_a_failed_release_dispatch_does_not_fail_the_flag_save(self) -> None:
        self.client.post(self._url("import_all/"))
        with (
            patch(
                "products.release.backend.tasks.tasks.create_release_for_new_flag.apply_async",
                side_effect=ConnectionError("broker down"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            flag_id = self._flag("quiet-theme")

        assert flag_id

    def test_a_deleted_automatic_release_stays_deleted_when_its_flag_returns(self) -> None:
        self.client.post(self._url("import_all/"))
        with patch(FLAG_PATCH, return_value=True), self.captureOnCommitCallbacks(execute=True):
            flag_id = self._flag("quiet-theme")
        release_id = self.client.get(self._url()).json()["results"][0]["id"]
        self.client.delete(self._url(f"{release_id}/"))

        for active in (False, True):
            with patch(FLAG_PATCH, return_value=True), self.captureOnCommitCallbacks(execute=True):
                self.client.patch(
                    f"/api/projects/{self.team.id}/feature_flags/{flag_id}/", {"active": active}, format="json"
                )

        assert self.client.get(self._url()).json()["results"] == []

    @parameterized.expand(
        [
            ("enabled", True, False, True, ["Quiet theme"]),
            ("disabled", False, False, True, []),
            ("activated_later", True, True, True, ["Quiet theme"]),
            ("project_never_opened_releases", True, False, False, []),
        ]
    )
    def test_a_new_flag_gets_its_own_release(
        self, _name: str, enabled: bool, starts_inactive: bool, imported: bool, expected: list[str]
    ) -> None:
        if imported:
            self.client.post(self._url("import_all/"))
        with patch(FLAG_PATCH, return_value=enabled), self.captureOnCommitCallbacks(execute=True):
            flag_id = self._flag("quiet-theme", active=not starts_inactive)
        if starts_inactive:
            assert self.client.get(self._url()).json()["results"] == []
            with patch(FLAG_PATCH, return_value=enabled), self.captureOnCommitCallbacks(execute=True):
                self.client.patch(
                    f"/api/projects/{self.team.id}/feature_flags/{flag_id}/", {"active": True}, format="json"
                )

        assert [release["name"] for release in self.client.get(self._url()).json()["results"]] == expected
