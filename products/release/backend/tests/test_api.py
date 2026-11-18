from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value
from posthog.utils import generate_short_id

from products.product_analytics.backend.facade.api import get_or_create_saved_insight
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
            ("merge", "post", "00000000-0000-0000-0000-000000000000/merge/"),
            ("retrieve", "get", "00000000-0000-0000-0000-000000000000/"),
            ("flag_suggestions", "get", "flag_suggestions/?feature_flag_id=1"),
        ]
    )
    def test_every_action_is_closed_without_the_flag(self, _name: str, method: str, suffix: str) -> None:
        with patch(FLAG_PATCH, return_value=False):
            response = getattr(self.client, method)(self._url(suffix), {"name": "Dark mode"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()

    def _restrict_as_admin(self, resource_path: str, endpoint: str = "access_controls", **extra: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        restricted = self.client.put(
            f"/api/projects/{self.team.id}/{resource_path}/{endpoint}".rstrip("/"),
            {"access_level": "none", **extra},
            format="json",
        )
        assert restricted.status_code == status.HTTP_200_OK, restricted.json()

    def _linked_object(self, kind: str, name: str) -> tuple[str | int, str]:
        if kind == "broadcast":
            workflow_id = create_workflow_for_test(team_id=self.team.id, name=name).id
            return str(workflow_id), f"hog_flows/{workflow_id}"
        if kind == "survey":
            response = self.client.post(
                f"/api/projects/{self.team.id}/surveys/",
                {"name": name, "type": "popover", "questions": [{"type": "open", "question": "How is it?"}]},
                format="json",
            )
            assert response.status_code == status.HTTP_201_CREATED, response.json()
            return response.json()["id"], f"surveys/{response.json()['id']}"
        insight_id, _ = get_or_create_saved_insight(
            team_id=self.team.id,
            user_id=self.user.id,
            short_id=generate_short_id(),
            name=name,
            description=None,
            query=None,
        )
        return insight_id, f"insights/{insight_id}"

    @parameterized.expand(
        [
            (f"{kind}_{case}", kind, case, expected)
            for kind in ("broadcast", "survey", "insight")
            for case, expected in (
                ("existing", status.HTTP_201_CREATED),
                ("unknown", status.HTTP_400_BAD_REQUEST),
                ("hidden", status.HTTP_400_BAD_REQUEST),
            )
        ]
    )
    def test_linked_objects_must_exist_and_be_visible(self, _name: str, kind: str, case: str, expected: int) -> None:
        field = f"{kind}_ids"
        linked_id: str | int = 999999 if kind == "insight" else "00000000-0000-0000-0000-000000000001"
        if case in ("existing", "hidden"):
            linked_id, resource_path = self._linked_object(kind, "Launch")
        if case == "hidden":
            self._restrict_as_admin(resource_path)
            self.client.force_login(self._create_user("member@example.com"))

        response = self.client.post(self._url(), {"name": "Dark mode", field: [linked_id]}, format="json")

        assert response.status_code == expected, response.json()
        if expected == status.HTTP_201_CREATED:
            assert response.json()[field] == [linked_id]

    def test_a_deleted_linked_insight_stays_listed_until_unlinked(self) -> None:
        insight_id, _ = self._linked_object("insight", "Adoption")
        release_id = self.client.post(
            self._url(), {"name": "Dark mode", "insight_ids": [insight_id]}, format="json"
        ).json()["id"]
        deleted = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}/", {"deleted": True}, format="json"
        )
        assert deleted.status_code == status.HTTP_200_OK, deleted.json()

        listed = self.client.get(self._url()).json()["results"][0]
        unlinked = self.client.patch(self._url(f"{release_id}/"), {"insight_ids": []}, format="json")

        assert [(insight["id"], insight["deleted"]) for insight in listed["insights"]] == [(insight_id, True)]
        assert unlinked.status_code == status.HTTP_200_OK, unlinked.json()
        assert unlinked.json()["insight_ids"] == []

    @parameterized.expand([("survey",), ("insight",)])
    def test_hidden_surveys_and_insights_are_omitted_and_kept_on_update(self, kind: str) -> None:
        field = f"{kind}_ids"
        visible_id, _ = self._linked_object(kind, "Visible")
        hidden_id, hidden_path = self._linked_object(kind, "Hidden")
        detail = self.client.get(f"/api/projects/{self.team.id}/{kind}s/{visible_id}/").json()
        summary_fields = {
            "survey": ("name", "created_at", "start_date", "end_date", "linked_flag_id", "archived"),
            "insight": ("short_id", "name", "created_at", "last_modified_at", "deleted"),
        }[kind]
        release_id = self.client.post(
            self._url(), {"name": "Dark mode", field: [visible_id, hidden_id]}, format="json"
        ).json()["id"]
        self._restrict_as_admin(hidden_path)
        self.client.force_login(self._create_user("member@example.com"))

        unknown_id: str | int = 999999 if kind == "insight" else "00000000-0000-0000-0000-000000000001"
        member_view = self.client.get(self._url()).json()["results"][0]
        guessed_linked = self.client.patch(self._url(f"{release_id}/"), {field: [visible_id, hidden_id]}, format="json")
        guessed_unknown = self.client.patch(
            self._url(f"{release_id}/"), {field: [visible_id, unknown_id]}, format="json"
        )
        self.client.patch(self._url(f"{release_id}/"), {field: []}, format="json")
        stored = getattr(Release.objects.unscoped().get(id=release_id), field)

        assert member_view[field] == [visible_id]
        assert member_view[f"{kind}s"] == [{"id": visible_id, **{key: detail[key] for key in summary_fields}}]
        assert guessed_linked.status_code == guessed_unknown.status_code == status.HTTP_400_BAD_REQUEST
        assert field in guessed_unknown.json()["attr"]
        assert [str(item) for item in stored] == [str(hidden_id)]

    def test_metrics_keep_their_order_and_a_hidden_metric_survives_an_update(self) -> None:
        primary, _ = self._linked_object("insight", "Weekly checkouts")
        secondary, _ = self._linked_object("insight", "Checkout errors")
        hidden, hidden_path = self._linked_object("insight", "Revenue")
        release_id = self.client.post(
            self._url(), {"name": "Checkout", "metric_insight_ids": [primary, hidden, secondary]}, format="json"
        ).json()["id"]
        extra = [self._linked_object("insight", f"Metric {index}")[0] for index in range(3)]
        self._restrict_as_admin(hidden_path)
        self.client.force_login(self._create_user("member@example.com"))

        member_view = self.client.get(self._url()).json()["results"][0]
        self.client.patch(self._url(f"{release_id}/"), {"metric_insight_ids": [secondary, primary]}, format="json")
        over_cap = self.client.patch(
            self._url(f"{release_id}/"), {"metric_insight_ids": [secondary, primary, *extra]}, format="json"
        )
        stored = Release.objects.unscoped().get(id=release_id).metric_insight_ids

        assert member_view["metric_insight_ids"] == [primary, secondary]
        assert over_cap.status_code == status.HTTP_400_BAD_REQUEST
        assert "metric_insight_ids" in over_cap.json()["attr"]
        assert stored == [secondary, primary, hidden]

    @parameterized.expand(
        [
            ("too_many", lambda ids: ids * 2),
            ("duplicate", lambda ids: [ids[0], ids[0]]),
            ("unknown", lambda ids: [999999]),
        ]
    )
    def test_metrics_reject_bad_lists(self, _name: str, build) -> None:
        ids = [self._linked_object("insight", f"Metric {index}")[0] for index in range(3)]

        response = self.client.post(self._url(), {"name": "Checkout", "metric_insight_ids": build(ids)}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "metric_insight_ids" in response.json()["attr"]

    def test_metric_goals_follow_their_metrics_and_a_hidden_metric_s_goal_survives(self) -> None:
        primary, _ = self._linked_object("insight", "Weekly checkouts")
        secondary, _ = self._linked_object("insight", "Checkout errors")
        hidden, hidden_path = self._linked_object("insight", "Revenue")
        release_id = self.client.post(
            self._url(),
            {
                "name": "Checkout",
                "metric_insight_ids": [primary, secondary, hidden],
                "metric_goals": [
                    {"insight_id": primary, "direction": "at_least", "value": 100},
                    {"insight_id": hidden, "direction": "at_least", "value": 5000},
                ],
            },
            format="json",
        ).json()["id"]
        self._restrict_as_admin(hidden_path)
        self.client.force_login(self._create_user("member@example.com"))

        member_view = self.client.get(self._url()).json()["results"][0]
        updated = self.client.patch(
            self._url(f"{release_id}/"),
            {"metric_goals": [{"insight_id": secondary, "direction": "at_most", "value": 2.5}]},
            format="json",
        ).json()
        not_a_metric = self.client.patch(
            self._url(f"{release_id}/"),
            {"metric_goals": [{"insight_id": 999999, "direction": "at_least", "value": 1}]},
            format="json",
        )
        on_hidden = self.client.patch(
            self._url(f"{release_id}/"),
            {"metric_goals": [{"insight_id": hidden, "direction": "at_least", "value": 1}]},
            format="json",
        )
        self.client.patch(self._url(f"{release_id}/"), {"metric_insight_ids": [primary]}, format="json")
        stored = Release.objects.unscoped().get(id=release_id).metric_goals

        assert member_view["metric_goals"] == [{"insight_id": primary, "direction": "at_least", "value": 100}]
        assert updated["metric_goals"] == [{"insight_id": secondary, "direction": "at_most", "value": 2.5}]
        assert not_a_metric.status_code == on_hidden.status_code == status.HTTP_400_BAD_REQUEST
        assert "metric_goals" in on_hidden.json()["attr"]
        assert stored == [{"insight_id": hidden, "direction": "at_least", "value": 5000}]

    def test_merge_keeps_the_kept_release_s_primary_metric_and_caps_the_list(self) -> None:
        ids = [self._linked_object("insight", f"Metric {index}")[0] for index in range(6)]
        kept = self.client.post(self._url(), {"name": "Checkout", "metric_insight_ids": ids[:3]}, format="json").json()[
            "id"
        ]
        other = self.client.post(
            self._url(), {"name": "Payments", "metric_insight_ids": [ids[2], *ids[3:]]}, format="json"
        ).json()["id"]

        merged = self.client.post(self._url(f"{kept}/merge/"), {"release_ids": [other]}, format="json")

        assert merged.status_code == status.HTTP_200_OK, merged.json()
        assert merged.json()["metric_insight_ids"] == ids[:5]

    @parameterized.expand(
        [
            (f"{kind}_{name}", kind, scopes, shown)
            for kind, scope in (("survey", "survey:read"), ("insight", "insight:read"))
            for name, scopes, shown in (
                ("flags_only", ["feature_flag:read"], False),
                ("flags_and_resource", ["feature_flag:read", scope], True),
                ("full_access", ["*"], True),
            )
        ]
    )
    def test_surveys_and_insights_follow_their_scope(
        self, _name: str, kind: str, scopes: list[str], shown: bool
    ) -> None:
        field = f"{kind}_ids"
        linked_id, _ = self._linked_object(kind, "Launch")
        self.client.post(self._url(), {"name": "Dark mode", field: [linked_id]}, format="json")
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()

        release = self.client.get(self._url(), HTTP_AUTHORIZATION=f"Bearer {token}").json()["results"][0]

        assert release[field] == ([linked_id] if shown else [])
        assert [item["id"] for item in release[f"{kind}s"]] == ([linked_id] if shown else [])

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
        visible_id = self._flag("launch-copy")
        self.client.patch(self._url(f"{release_id}/"), {"feature_flag_ids": [flag_id, visible_id]}, format="json")
        if renamed:
            self.client.patch(self._url(f"{release_id}/"), {"name": "Checkout"}, format="json")
        self._restrict_as_admin(f"feature_flags/{flag_id}")
        self.client.force_login(self._create_user("member@example.com"))

        assert self.client.get(self._url()).json()["results"][0]["name"] == expected
        assert [release["name"] for release in self.client.get(self._url("catalog_releases/")).json()["results"]] == [
            expected
        ]
        assert self.client.get(self._url("catalog_releases/?search=secret")).json()["results"] == []
        assert self.client.get(self._url(f"{release_id}/")).json()["name"] == expected
        assert self.client.get(self._url(f"catalog_releases/?feature_flag_id={flag_id}")).json()["results"] == []
        assert self.client.get(self._url(f"flag_suggestions/?feature_flag_id={flag_id}")).status_code == 404
        current = self.client.get(self._url(f"flag_suggestions/?feature_flag_id={visible_id}")).json()["current"]
        assert [release["name"] for release in current if release["id"] == release_id] == [expected]

    def test_retrieve_and_catalog_filter_find_a_release_by_its_flag(self) -> None:
        flag_id = self._flag("checkout-button")
        linked = self.client.post(
            self._url(), {"name": "Checkout", "feature_flag_ids": [flag_id]}, format="json"
        ).json()
        self.client.post(self._url(), {"name": "Billing"}, format="json")

        assert self.client.get(self._url(f"{linked['id']}/")).json()["feature_flag_ids"] == [flag_id]
        assert self.client.get(self._url(f"{uuid4()}/")).status_code == status.HTTP_404_NOT_FOUND
        assert [
            release["name"]
            for release in self.client.get(self._url(f"catalog_releases/?feature_flag_id={flag_id}")).json()["results"]
        ] == ["Checkout"]

    def test_flag_suggestions_rank_related_releases_and_list_the_ones_it_is_in(self) -> None:
        flag_id = self._flag("checkout-redesign-button")
        copy_flag = self._flag("checkout-copy")
        self.client.post(self._url(), {"name": "Checkout"}, format="json")
        self.client.post(self._url(), {"name": "Payments", "feature_flag_ids": [copy_flag]}, format="json")
        self.client.post(self._url(), {"name": "Pricing page"}, format="json")
        self.client.post(self._url(), {"name": "Button styles", "feature_flag_ids": [flag_id]}, format="json")

        response = self.client.get(self._url(f"flag_suggestions/?feature_flag_id={flag_id}"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert [release["name"] for release in body["current"]] == ["Button styles"]
        assert body["auto_release"] is False
        assert [(release["name"], release["matched_terms"]) for release in body["suggestions"]] == [
            ("Checkout", ["checkout"]),
            ("Payments", ["checkout"]),
        ]

    def test_flag_suggestions_never_match_through_flags_the_caller_cannot_see(self) -> None:
        flag_id = self._flag("checkout-redesign")
        secret = self._flag("checkout-secret")
        self.client.post(self._url("import_all/"))
        self.client.post(self._url(), {"name": "Redesign", "feature_flag_ids": [secret]}, format="json")
        self._restrict_as_admin(f"feature_flags/{secret}")
        self.client.force_login(self._create_user("member@example.com"))

        body = self.client.get(self._url(f"flag_suggestions/?feature_flag_id={flag_id}")).json()

        assert [(release["name"], release["matched_terms"]) for release in body["suggestions"]] == [
            ("Redesign", ["redesign"])
        ]

    @parameterized.expand([("active", True, True), ("inactive", False, False)])
    def test_flag_suggestions_say_whether_the_flag_gets_its_own_release(
        self, _name: str, active: bool, expected: bool
    ) -> None:
        self.client.post(self._url("import_all/"))
        flag_id = self._flag("checkout-express", active=active)

        body = self.client.get(self._url(f"flag_suggestions/?feature_flag_id={flag_id}")).json()

        assert body["auto_release"] is expected

    def test_flag_suggestions_return_404_for_an_unknown_or_deleted_flag(self) -> None:
        deleted = self._flag("checkout-old")
        self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{deleted}/", {"deleted": True}, format="json")

        for flag_id in (999999, deleted):
            response = self.client.get(self._url(f"flag_suggestions/?feature_flag_id={flag_id}"))
            assert response.status_code == status.HTTP_404_NOT_FOUND, flag_id

    def test_catalog_releases_search_gives_no_hint_of_restricted_generated_names(self) -> None:
        hidden = [self._flag(key) for key in ("secret-launch", "secret-pricing")]
        self.client.post(self._url("import_all/"))
        for flag_id in hidden:
            self._restrict_as_admin(f"feature_flags/{flag_id}")
        self.client.force_login(self._create_user("member@example.com"))

        response = self.client.get(self._url("catalog_releases/?search=secret&limit=1"))

        assert response.json() == {"results": [], "next_cursor": None}

    def test_merge_moves_every_link_into_the_kept_release_and_deletes_the_others(self) -> None:
        flags = [self._flag(key) for key in ("checkout-button", "checkout-copy", "checkout-form")]
        survey_id, _ = self._linked_object("survey", "Checkout feedback")
        kept = Release.objects.unscoped().create(team=self.team, name="Checkout", feature_flag_ids=[flags[0]])
        copy = Release.objects.unscoped().create(
            team=self.team,
            name="Checkout copy",
            description="Shorter labels.",
            owner=self.user,
            feature_flag_ids=[flags[1], flags[0]],
            survey_ids=[survey_id],
        )
        form = Release.objects.unscoped().create(team=self.team, name="Checkout form", feature_flag_ids=[flags[2]])

        response = self.client.post(
            self._url(f"{kept.id}/merge/"),
            {"release_ids": [str(copy.id), str(form.id)], "name": "Checkout v2"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = response.json()
        assert (body["name"], body["description"], body["owner"]["id"]) == (
            "Checkout v2",
            "Shorter labels.",
            self.user.id,
        )
        assert body["feature_flag_ids"] == flags
        assert body["survey_ids"] == [survey_id]
        assert list(Release.objects.unscoped().filter(team=self.team).values_list("id", flat=True)) == [kept.id]

    @parameterized.expand(
        [
            ("only_itself", "self", status.HTTP_400_BAD_REQUEST),
            ("unknown_release", "unknown", status.HTTP_400_BAD_REQUEST),
            ("hidden_flag", "hidden", status.HTTP_400_BAD_REQUEST),
            ("missing_target", "missing_target", status.HTTP_404_NOT_FOUND),
            ("too_many_links", "too_many", status.HTTP_400_BAD_REQUEST),
        ]
    )
    def test_merge_rejects_what_it_cannot_combine(self, _name: str, case: str, expected: int) -> None:
        flag_id = self._flag("checkout-copy")
        kept = Release.objects.unscoped().create(team=self.team, name="Checkout")
        other = Release.objects.unscoped().create(team=self.team, name="Checkout copy", feature_flag_ids=[flag_id])
        target_id, source_id = str(kept.id), str(other.id)
        if case == "self":
            source_id = target_id
        elif case == "unknown":
            source_id = "00000000-0000-0000-0000-000000000001"
        elif case == "missing_target":
            target_id = "00000000-0000-0000-0000-000000000002"
        elif case == "too_many":
            Release.objects.unscoped().filter(id=kept.id).update(insight_ids=list(range(1, 61)))
            Release.objects.unscoped().filter(id=other.id).update(insight_ids=list(range(50, 102)))
        elif case == "hidden":
            self._restrict_as_admin(f"feature_flags/{flag_id}")
            self.client.force_login(self._create_user("member@example.com"))

        response = self.client.post(self._url(f"{target_id}/merge/"), {"release_ids": [source_id]}, format="json")

        assert response.status_code == expected, response.json()
        assert Release.objects.unscoped().filter(team=self.team).count() == 2

    def test_catalog_flags_lists_visible_flags_newest_first_with_search_and_paging(self) -> None:
        older = self._flag("checkout-copy")
        newer = self._flag("checkout-button")
        self._flag("pricing-page")
        archived = self._flag("checkout-archived")
        self.client.patch(
            f"/api/projects/{self.team.id}/feature_flags/{archived}/",
            {"archived": True, "active": False},
            format="json",
        )
        deleted = self._flag("checkout-deleted")
        self.client.patch(f"/api/projects/{self.team.id}/feature_flags/{deleted}/", {"deleted": True}, format="json")

        first = self.client.get(self._url("catalog_flags/?search=checkout&limit=1")).json()
        second = self.client.get(self._url("catalog_flags/?search=checkout&limit=1&offset=1")).json()

        assert [flag["id"] for flag in first["results"]] == [newer]
        assert first["has_more"] is True
        assert [flag["id"] for flag in second["results"]] == [older]
        assert second["has_more"] is False
        assert first["results"][0]["created_by"]["id"] == self.user.id

        oldest = self.client.get(self._url("catalog_flags/?search=checkout&order=created_at")).json()
        assert [flag["id"] for flag in oldest["results"]] == [older, newer]

        other = self._create_user("someone@example.com")
        assert self.client.get(self._url(f"catalog_flags/?created_by={other.id}")).json()["results"] == []
        assert self.client.get(self._url("catalog_flags/?created_by=nope")).status_code == status.HTTP_400_BAD_REQUEST

    def test_catalog_releases_lists_newest_first_with_search_and_paging(self) -> None:
        other = self._create_user("someone@example.com")
        for name in ("Checkout older", "Billing", "Checkout newer"):
            Release.objects.unscoped().create(team=self.team, name=name, owner=other if name == "Billing" else None)

        first = self.client.get(self._url("catalog_releases/?search=checkout&limit=1")).json()
        second = self.client.get(
            self._url("catalog_releases/"), {"search": "checkout", "limit": "1", "cursor": first["next_cursor"]}
        ).json()

        assert [release["name"] for release in first["results"]] == ["Checkout newer"]
        assert [release["name"] for release in second["results"]] == ["Checkout older"]
        assert second["next_cursor"] is None
        assert self.client.get(self._url("catalog_releases/?cursor=bad")).status_code == status.HTTP_400_BAD_REQUEST

        oldest = self.client.get(self._url("catalog_releases/?order=created_at&limit=1")).json()
        after = self.client.get(
            self._url("catalog_releases/"), {"order": "created_at", "limit": "1", "cursor": oldest["next_cursor"]}
        ).json()
        assert [release["name"] for release in oldest["results"] + after["results"]] == ["Checkout older", "Billing"]

        owned = self.client.get(self._url(f"catalog_releases/?owner={other.id}")).json()["results"]
        assert [(release["name"], release["owner"]["id"]) for release in owned] == [("Billing", other.id)]

    def test_catalog_flags_hides_flags_the_caller_cannot_see(self) -> None:
        visible = self._flag("checkout-visible")
        hidden = self._flag("checkout-hidden")
        self._restrict_as_admin(f"feature_flags/{hidden}")
        self.client.force_login(self._create_user("member@example.com"))

        response = self.client.get(self._url("catalog_flags/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [flag["id"] for flag in response.json()["results"]] == [visible]

    def test_catalog_flags_lists_flags_granted_one_by_one_without_resource_access(self) -> None:
        granted = self._flag("checkout-granted")
        self._flag("checkout-other")
        member = self._create_user("member@example.com")
        self._restrict_as_admin("resource_access_controls", endpoint="", resource="feature_flag")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        grant = self.client.put(
            f"/api/projects/{self.team.id}/feature_flags/{granted}/access_controls",
            {"organization_member": str(membership.id), "access_level": "viewer"},
            format="json",
        )
        assert grant.status_code == status.HTTP_200_OK, grant.json()
        self.client.force_login(member)

        response = self.client.get(self._url("catalog_flags/"))

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [flag["id"] for flag in response.json()["results"]] == [granted]

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
            ("merge", "post", "feature_flag:write", status.HTTP_200_OK),
            ("merge", "post", "feature_flag:read", status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_write_actions_follow_feature_flag_scopes(
        self, action: str, method: str, scope: str, expected: int
    ) -> None:
        self._flag("checkout-v2")
        url, data = self._url(f"{action}/"), {}
        if action == "merge":
            kept = Release.objects.unscoped().create(team=self.team, name="Checkout")
            other = Release.objects.unscoped().create(team=self.team, name="Checkout copy")
            url, data = self._url(f"{kept.id}/merge/"), {"release_ids": [str(other.id)]}
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(token), scopes=[scope])
        self.client.logout()

        response = getattr(self.client, method)(url, data, format="json", HTTP_AUTHORIZATION=f"Bearer {token}")

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
