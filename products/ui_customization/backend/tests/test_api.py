from copy import deepcopy
from typing import TYPE_CHECKING, Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db import OperationalError, connections, router

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value

from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.models import Notebook
from products.ui_customization.backend.facade import api as customization_facade
from products.ui_customization.backend.facade.enums import CustomizationContext
from products.ui_customization.backend.facade.tasks import delete_orphaned_fragments
from products.ui_customization.backend.logic.cleanup import delete_orphaned_fragment_batch
from products.ui_customization.backend.models import UserInterfaceFragment
from products.ui_customization.backend.tests.conftest import UICustomizationTeamScopedTestMixin
from products.ui_customization.backend.tests.test_analytics_sidebar import GROWTH_LAYOUT

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

INSIGHT_IS_TRENDS = {"aB3dE5fG": True, "fUnN3l00": False}


class TestUICustomizationAPI(UICustomizationTeamScopedTestMixin, APIBaseTest):
    databases = {"default", "ui_customization_db_writer", "ui_customization_db_reader"}

    def setUp(self) -> None:
        super().setUp()
        insights = patch(
            "products.product_analytics.backend.facade.api.viewable_insights_are_trends",
            side_effect=lambda *, team, user, short_ids: {
                short_id: INSIGHT_IS_TRENDS[short_id] for short_id in short_ids if short_id in INSIGHT_IS_TRENDS
            },
        )
        insights.start()
        self.addCleanup(insights.stop)
        Notebook.objects.create(team=self.team, short_id="Zx9Yw8Vu", title="Launch notes")
        Notebook.objects.create(team=self.team, short_id="dEl3t3d0", title="Old notes", deleted=True)
        self.layout = deepcopy(GROWTH_LAYOUT)
        self.layout["sections"][0]["items"][1]["to"]["id"] = Dashboard.objects.create(team=self.team, name="Growth").id

    def _call(
        self, method: str, body: dict | None = None, flag: bool = True, context: str = "analytics_sidebar"
    ) -> "_MonkeyPatchedResponse":
        with patch(
            "products.ui_customization.backend.facade.feature_flags.posthog_feature_flag_value", return_value=flag
        ):
            return getattr(self.client, method)(
                f"/api/projects/{self.team.id}/ui_customization/{context}/", body, format="json"
            )

    def test_description_returns_a_valid_starting_point_without_fragment_storage(self) -> None:
        with (
            self.assertNumQueries(0, using="ui_customization_db_writer"),
            self.assertNumQueries(0, using="ui_customization_db_reader"),
        ):
            response = self._call("get", context="analytics_sidebar/schema")
        assert response.status_code == 200
        description = response.json()
        assert description["context"] == "analytics_sidebar"
        assert "$defs" in description["layout_schema"]
        saved = self._call("put", {"layout": description["default_layout"]})
        assert saved.status_code == 200
        assert saved.json()["layout"] == description["default_layout"]

    @parameterized.expand(
        [
            ("read", ["user:read"], True, "analytics_sidebar", False, 200),
            ("wrong_scope", ["today:read"], True, "analytics_sidebar", False, 403),
            ("flag_off", ["user:read"], False, "analytics_sidebar", False, 404),
            ("unknown", ["user:read"], True, "unknown", False, 404),
            ("wrong_project", ["user:read"], True, "analytics_sidebar", True, 403),
        ]
    )
    def test_description_respects_context_flag_and_token_access(
        self, _name: str, scopes: list[str], flag: bool, context: str, wrong_project: bool, expected: int
    ) -> None:
        allowed_team = Team.objects.create(organization=self.organization) if wrong_project else self.team
        raw_key = "synthetic_ui_description_key"
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Customization description",
            secure_value=hash_key_value(raw_key),
            scopes=scopes,
            scoped_teams=[allowed_team.id],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        assert self._call("get", flag=flag, context=f"{context}/schema").status_code == expected

    @parameterized.expand([("get",), ("put",), ("delete",)])
    def test_unknown_context_does_not_read_or_change_stored_fragments(self, method: str) -> None:
        fragment = UserInterfaceFragment.objects.create(
            team_id=self.team.id, user_id=self.user.id, context="unknown", content=GROWTH_LAYOUT
        )
        with self.assertNumQueries(0, using="ui_customization_db_writer"):
            with self.assertNumQueries(0, using="ui_customization_db_reader"):
                response = self._call(method, {"layout": GROWTH_LAYOUT} if method == "put" else None, context="unknown")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        fragment.refresh_from_db()
        assert fragment.content == GROWTH_LAYOUT

    def _section_ids(self, response: "_MonkeyPatchedResponse") -> tuple[bool, list[str]]:
        body = response.json()
        return body["customized"], [section["id"] for section in body["layout"]["sections"]]

    def test_a_person_saves_and_resets_their_own_layout_without_changing_anyone_elses(self) -> None:
        other_fragment = UserInterfaceFragment.objects.create(
            team_id=self.team.id, user_id=self.user.id, context="OtherSurface", content={"title": "Other surface"}
        )
        default = (False, ["browse", "pinned", "recents", "by-posthog", "monitor"])
        before = self._section_ids(self._call("get"))
        saved = self._call("put", {"layout": self.layout})
        read = self._call("get")
        self.client.force_login(self._create_user("teammate@example.com"))
        teammate = self._section_ids(self._call("get"))
        self.client.force_login(self.user)
        reset = self._section_ids(self._call("delete"))
        after = self._section_ids(self._call("get"))

        assert (before, saved.json(), read.json(), teammate, reset, after) == (
            default,
            {"layout": self.layout, "customized": True},
            {"layout": self.layout, "customized": True},
            default,
            default,
            default,
        )
        other_fragment.refresh_from_db()
        assert other_fragment.content == {"title": "Other surface"}

    def test_child_environments_share_the_parent_team_layout(self) -> None:
        child = Team.objects.create(
            organization=self.organization, project=self.team.project, parent_team=self.team, name="Child"
        )
        self._call("put", {"layout": self.layout})

        assert (
            customization_facade.get_customization(
                team=child, user=self.user, context="analytics_sidebar"
            ).layout.model_dump(mode="json", exclude_none=True)
            == self.layout
        )
        customization_facade.reset_customization(team=child, user=self.user, context="analytics_sidebar")

        assert self._call("get").json()["customized"] is False

    @parameterized.expand([("api",), ("orm",)])
    def test_account_cleanup_after_leaving_organization_preserves_other_users(self, deletion: str) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        teammate = self._create_user("remaining-user@example.com")
        self._call("put", {"layout": GROWTH_LAYOUT})
        for team_id in [self.team.id, other_team.id]:
            for user_id in [self.user.id, teammate.id]:
                UserInterfaceFragment.objects.for_team(team_id).create(
                    team_id=team_id, user_id=user_id, context="OtherSurface", content={}
                )
        OrganizationMembership.objects.filter(user=self.user).delete()
        deleted_user_id = self.user.id
        if deletion == "api":
            assert self.client.delete("/api/users/@me/").status_code == 204
        else:
            User.objects.filter(id=deleted_user_id).delete()

        with (
            patch("products.ui_customization.backend.logic.cleanup.BATCH_SIZE", 2),
            patch.object(delete_orphaned_fragments, "delay", side_effect=delete_orphaned_fragments.run),
        ):
            delete_orphaned_fragments.run()
        assert not User.objects.filter(id=deleted_user_id).exists()
        assert set(UserInterfaceFragment.objects.unscoped().values_list("team_id", "user_id", "context")) == {
            (team_id, teammate.id, "OtherSurface") for team_id in [self.team.id, other_team.id]
        }
        assert Team.objects.filter(id__in=[self.team.id, other_team.id]).count() == 2

    def test_account_cleanup_failure_keeps_rows_and_next_sweep_recovers_late_writes(self) -> None:
        deleted_user = self._create_user("removed-user@example.com")
        deleted_user_id = deleted_user.id
        deleted_user.delete()
        orphan = UserInterfaceFragment.objects.create(
            team_id=self.team.id, user_id=deleted_user_id, context="OtherSurface", content={}
        )
        self._call("put", {"layout": self.layout})

        def fail_user_lookup(execute, sql, params, many, context):
            if 'FROM "posthog_user"' in sql:
                raise OperationalError("User database unavailable")
            return execute(sql, params, many, context)

        with connections[router.db_for_write(User)].execute_wrapper(fail_user_lookup):
            with self.assertRaisesRegex(OperationalError, "User database unavailable"):
                delete_orphaned_fragment_batch()
        assert UserInterfaceFragment.objects.filter(id=orphan.id).exists()

        delete_orphaned_fragment_batch()
        assert not UserInterfaceFragment.objects.filter(id=orphan.id).exists()
        assert UserInterfaceFragment.objects.filter(user_id=self.user.id).exists()
        UserInterfaceFragment.objects.create(
            team_id=self.team.id, user_id=deleted_user_id, context="LateWrite", content={}
        )
        delete_orphaned_fragment_batch()
        assert list(UserInterfaceFragment.objects.values_list("user_id", flat=True)) == [self.user.id]

    def test_team_deletion_removes_all_fragment_contexts_and_users_only_for_that_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        teammate = self._create_user("fragment-teammate@example.com")
        for team_id in [self.team.id, other_team.id]:
            for user_id in [self.user.id, teammate.id]:
                for context in [CustomizationContext.ANALYTICS_SIDEBAR, "OtherSurface"]:
                    UserInterfaceFragment.objects.for_team(team_id).create(
                        team_id=team_id, user_id=user_id, context=context, content={"title": context}
                    )

        customization_facade.delete_fragments_for_teams([self.team.id])
        customization_facade.delete_fragments_for_teams([self.team.id])

        assert not UserInterfaceFragment.objects.for_team(self.team.id).exists()
        assert set(UserInterfaceFragment.objects.for_team(other_team.id).values_list("user_id", "context")) == {
            (user_id, context)
            for user_id in [self.user.id, teammate.id]
            for context in [CustomizationContext.ANALYTICS_SIDEBAR, "OtherSurface"]
        }

    @parameterized.expand(
        [
            (
                "outside the schema",
                [(0, 0, {"type": "link", "to": {"kind": "url", "url": "https://example.com"}})],
                ["sections.0.items.0.link.to"],
            ),
            (
                "every unavailable target",
                [
                    (0, 0, {"type": "metric", "insight": "fUnN3l00", "label": "Checkout"}),
                    (0, 1, {"type": "link", "to": {"kind": "dashboard", "id": 999999}, "label": "Gone"}),
                    (0, 2, {"type": "link", "to": {"kind": "notebook", "short_id": "dEl3t3d0"}, "label": "Old"}),
                    (0, 3, {"type": "button", "to": {"kind": "insight", "short_id": "nOtH3r3"}, "label": "Missing"}),
                ],
                [
                    "sections.0.items.0.insight: Insight fUnN3l00 is not a trends insight",
                    "sections.0.items.1.to: No dashboard 999999",
                    "sections.0.items.2.to: No notebook dEl3t3d0",
                    "sections.0.items.3.to: No insight nOtH3r3",
                ],
            ),
        ]
    )
    def test_a_layout_it_cannot_show_is_rejected_and_names_every_value(
        self, _name: str, replacements: list[tuple[int, int, dict[str, Any]]], expected: list[str]
    ) -> None:
        layout = deepcopy(self.layout)
        for section, index, item in replacements:
            layout["sections"][section]["items"][index] = item

        response = self._call("put", {"layout": layout})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()["detail"]
        assert all(message in detail for message in expected), detail
        assert not UserInterfaceFragment.objects.for_team(self.team.id).exists()

    def test_a_stored_layout_the_schema_no_longer_accepts_shows_the_default_and_stays_stored(self) -> None:
        stored = {"sections": [{"id": "x", "items": [{"type": "retired_widget"}]}]}
        UserInterfaceFragment.objects.create(
            team_id=self.team.id, user_id=self.user.id, context=CustomizationContext.ANALYTICS_SIDEBAR, content=stored
        )

        response = self._call("get")

        assert (response.json()["customized"], UserInterfaceFragment.objects.get(user_id=self.user.id).content) == (
            False,
            stored,
        )

    @parameterized.expand([("get", None), ("put", {"layout": GROWTH_LAYOUT}), ("delete", None)])
    def test_people_without_ui_customization_get_404(self, method: str, body: dict | None) -> None:
        assert self._call(method, body, flag=False).status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("get", ["user:read"], 200),
            ("put", ["user:read"], 403),
            ("delete", ["user:read"], 403),
            ("put", ["user:write"], 200),
            ("delete", ["user:write"], 200),
            ("get", ["today:read"], 403),
            ("put", ["today:write"], 403),
        ]
    )
    def test_scoped_keys_require_user_preference_scopes(self, method: str, scopes: list[str], expected: int) -> None:
        raw_key = "synthetic_ui_customization_key"
        PersonalAPIKey.objects.create(
            user=self.user, label="UI customization", secure_value=hash_key_value(raw_key), scopes=scopes
        )
        self.client.logout()
        with patch(
            "products.ui_customization.backend.facade.feature_flags.posthog_feature_flag_value", return_value=True
        ):
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/ui_customization/analytics_sidebar/",
                {"layout": self.layout} if method == "put" else None,
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {raw_key}",
            )
        assert response.status_code == expected

    @parameterized.expand(
        [(method, restriction) for method in ["get", "put", "delete"] for restriction in ["project", "organization"]]
    )
    def test_scoped_keys_only_access_their_allowed_tenant(self, method: str, restriction: str) -> None:
        other_org, _, other_team = Organization.objects.bootstrap(self.user)
        if restriction == "project":
            other_team = Team.objects.create(organization=self.organization, name="Other project")
        raw_key = "synthetic_ui_customization_restricted_key"
        key = PersonalAPIKey.objects.create(
            user=self.user,
            label="Restricted customization",
            secure_value=hash_key_value(raw_key),
            scopes=["user:read", "user:write"],
            scoped_teams=[other_team.id] if restriction == "project" else [],
            scoped_organizations=[str(other_org.id)] if restriction == "organization" else [],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        body = {"layout": self.layout} if method == "put" else None

        assert self._call(method, body).status_code == status.HTTP_403_FORBIDDEN
        assert not UserInterfaceFragment.objects.for_team(self.team.id).exists()

        key.scoped_teams = [self.team.id] if restriction == "project" else []
        key.scoped_organizations = [str(self.organization.id)] if restriction == "organization" else []
        key.save()

        assert self._call(method, body).status_code == status.HTTP_200_OK

    @parameterized.expand([("get",), ("put",), ("delete",)])
    def test_organization_personal_key_policy_applies_to_customization(self, method: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATION_SECURITY_SETTINGS, "name": "Security settings"}
        ]
        self.organization.members_can_use_personal_api_keys = False
        self.organization.save()
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).update(
            level=OrganizationMembership.Level.MEMBER
        )
        raw_key = "synthetic_ui_customization_policy_key"
        PersonalAPIKey.objects.create(
            user=self.user,
            label="Customization policy",
            secure_value=hash_key_value(raw_key),
            scopes=["user:read", "user:write"],
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw_key}")
        body = {"layout": self.layout} if method == "put" else None

        assert self._call(method, body).status_code == status.HTTP_403_FORBIDDEN
        assert not UserInterfaceFragment.objects.for_team(self.team.id).exists()

        self.organization.members_can_use_personal_api_keys = True
        self.organization.save()

        assert self._call(method, body).status_code == status.HTTP_200_OK

    @parameterized.expand([("get", None), ("put", {"layout": GROWTH_LAYOUT}), ("delete", None)])
    def test_navigation_flag_alone_does_not_enable_customization(self, method: str, body: dict | None) -> None:
        with patch(
            "products.ui_customization.backend.facade.feature_flags.posthog_feature_flag_value",
            side_effect=lambda key, *args, **kwargs: key == "today-rail-nav",
        ):
            response = getattr(self.client, method)(
                f"/api/projects/{self.team.id}/ui_customization/analytics_sidebar/", body, format="json"
            )
        assert response.status_code == 404
