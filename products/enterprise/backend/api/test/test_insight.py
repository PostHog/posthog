from datetime import timedelta
from typing import Optional, cast

from freezegun import freeze_time
from posthog.test.base import FuzzyInt, snapshot_postgres_queries

from django.test import override_settings
from django.utils import timezone

from rest_framework import status

from posthog.api.test.dashboards import DashboardAPI
from posthog.models import Dashboard, DashboardTile, Insight, OrganizationMembership, User
from posthog.test.db_context_capturing import capture_db_queries

from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.models import DashboardPrivilege


class TestInsightEnterpriseAPI(APILicensedTest):
    def setUp(self) -> None:
        super().setUp()
        self.dashboard_api = DashboardAPI(self.client, self.team, self.assertEqual)

    @override_settings(IN_UNIT_TESTING=True)
    def test_can_add_and_remove_tags(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z"):
            insight_id, response_data = self.dashboard_api.create_insight(
                {
                    "name": "a created dashboard",
                    "filters": {
                        "events": [{"id": "$pageview"}],
                        "properties": [{"key": "$browser", "value": "Mac OS X"}],
                        "date_from": "-90d",
                    },
                }
            )
        insight_short_id = response_data["short_id"]
        self.assertEqual(response_data["tags"], [])

        with freeze_time("2012-01-14T03:21:35.000Z"):
            add_tags_response = self.client.patch(
                # tags are displayed in order of insertion
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"tags": ["2", "1", "3"]},
            )

        self.assertEqual(sorted(add_tags_response.json()["tags"]), ["1", "2", "3"])

        with freeze_time("2012-01-14T03:21:36.000Z"):
            remove_tags_response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}", {"tags": ["3"]}
            )

        self.assertEqual(remove_tags_response.json()["tags"], ["3"])

        self.assert_insight_activity(
            insight_id=insight_id,
            expected=[
                {
                    "activity": "updated",
                    "created_at": "2012-01-14T03:21:36Z",
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": ["3"],
                                "before": ["1", "2", "3"],
                                "field": "tags",
                                "type": "Insight",
                            }
                        ],
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "updated",
                    "created_at": "2012-01-14T03:21:35Z",
                    "detail": {
                        "changes": [
                            {
                                "action": "changed",
                                "after": ["1", "2", "3"],
                                "before": [],
                                "field": "tags",
                                "type": "Insight",
                            }
                        ],
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
                {
                    "activity": "created",
                    "created_at": "2012-01-14T03:21:34Z",
                    "detail": {
                        "changes": None,
                        "name": "a created dashboard",
                        "short_id": insight_short_id,
                        "trigger": None,
                        "type": None,
                    },
                    "item_id": str(insight_id),
                    "scope": "Insight",
                    "user": {"email": "user1@posthog.com", "first_name": ""},
                },
            ],
        )

    def test_update_insight_can_include_tags_when_licensed(self) -> None:
        with freeze_time("2012-01-14T03:21:34.000Z") as frozen_time:
            insight_id, insight = self.dashboard_api.create_insight({"name": "insight name"})
            short_id = insight["short_id"]

            frozen_time.tick(delta=timedelta(minutes=10))

            response = self.client.patch(
                f"/api/projects/{self.team.id}/insights/{insight_id}",
                {"name": "insight new name", "tags": ["add", "these", "tags"]},
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            response_data = response.json()
            self.assertEqual(response_data["name"], "insight new name")
            self.assertEqual(sorted(response_data["tags"]), sorted(["add", "these", "tags"]))
            self.assertEqual(response_data["created_by"]["distinct_id"], self.user.distinct_id)
            self.assertEqual(
                response_data["effective_restriction_level"],
                Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
            )
            self.assertEqual(
                response_data["effective_privilege_level"],
                Dashboard.PrivilegeLevel.CAN_EDIT,
            )

            response = self.client.get(f"/api/projects/{self.team.id}/insights/{insight_id}")

            self.assertEqual(response.json()["name"], "insight new name")

            self.assert_insight_activity(
                insight_id,
                [
                    {
                        "user": {"first_name": "", "email": "user1@posthog.com"},
                        "activity": "updated",
                        "scope": "Insight",
                        "item_id": str(insight_id),
                        "detail": {
                            "changes": [
                                {
                                    "type": "Insight",
                                    "action": "changed",
                                    "field": "tags",
                                    "before": [],
                                    "after": ["add", "tags", "these"],
                                },
                                {
                                    "type": "Insight",
                                    "action": "changed",
                                    "field": "name",
                                    "before": "insight name",
                                    "after": "insight new name",
                                },
                            ],
                            "trigger": None,
                            "type": None,
                            "name": "insight new name",
                            "short_id": short_id,
                        },
                        "created_at": "2012-01-14T03:31:34Z",
                    },
                    {
                        "user": {"first_name": "", "email": "user1@posthog.com"},
                        "activity": "created",
                        "scope": "Insight",
                        "item_id": str(insight_id),
                        "detail": {
                            "changes": None,
                            "trigger": None,
                            "type": None,
                            "name": "insight name",
                            "short_id": short_id,
                        },
                        "created_at": "2012-01-14T03:21:34Z",
                    },
                ],
            )

    def test_non_admin_user_with_privilege_can_add_an_insight_to_a_restricted_dashboard(
        self,
    ) -> None:
        # create insight and dashboard separately with default user
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        user_with_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="with_access_user@posthog.com",
            password=None,
        )

        DashboardPrivilege.objects.create(
            dashboard=dashboard_restricted,
            user=user_with_permissions,
            level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        self.client.force_login(user_with_permissions)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted.id]},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_an_insight_on_both_restricted_dashboard_does_not_restrict_with_explicit_privilege(
        self,
    ) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        DashboardPrivilege.objects.create(
            dashboard=dashboard_restricted,
            user=self.user,
            level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        _, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_cannot_update_restricted_insight_as_other_user_who_is_project_member(self):
        creator = User.objects.create_and_join(self.organization, "y@x.com", None)
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        original_name = "Edit-restricted dashboard"
        dashboard: Dashboard = Dashboard.objects.create(
            team=self.team,
            name=original_name,
            created_by=creator,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        insight: Insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.patch(f"/api/projects/{self.team.id}/insights/{insight.id}", {"name": "ABC"})
        response_data = response.json()
        dashboard.refresh_from_db()

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            response_data,
            self.permission_denied_response(
                "This insight is on a dashboard that can only be edited by its owner, team members invited to editing the dashboard, and project admins."
            ),
        )
        self.assertEqual(dashboard.name, original_name)

    def test_event_definition_no_duplicate_tags(self):
        from products.enterprise.backend.models.license import License, LicenseManager

        super(LicenseManager, cast(LicenseManager, License.objects)).create(
            key="key_123",
            plan="enterprise",
            valid_until=timezone.datetime(2038, 1, 19, 3, 14, 7),
        )
        dashboard = Dashboard.objects.create(team=self.team, name="Edit-restricted dashboard")
        insight = Insight.objects.create(team=self.team, name="XYZ", created_by=self.user)
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight.id}",
            {"tags": ["a", "b", "a"]},
        )

        self.assertListEqual(sorted(response.json()["tags"]), ["a", "b"])

    def test_searching_insights_includes_tags_and_description(self) -> None:
        insight_one_id, _ = self.dashboard_api.create_insight(
            {
                "name": "needle in a haystack",
                "filters": {"events": [{"id": "$pageview"}]},
            }
        )
        insight_two_id, _ = self.dashboard_api.create_insight(
            {"name": "not matching", "filters": {"events": [{"id": "$pageview"}]}}
        )

        insight_three_id, _ = self.dashboard_api.create_insight(
            {
                "name": "not matching name",
                "filters": {"events": [{"id": "$pageview"}]},
                "tags": ["needle"],
            }
        )

        insight_four_id, _ = self.dashboard_api.create_insight(
            {
                "name": "not matching name",
                "description": "another needle",
                "filters": {"events": [{"id": "$pageview"}]},
                "tags": ["not matching"],
            }
        )

        matching = self.client.get(f"/api/projects/{self.team.id}/insights/?search=needle")
        self.assertEqual(matching.status_code, status.HTTP_200_OK)
        matched_insights = [insight["id"] for insight in matching.json()["results"]]
        assert sorted(matched_insights) == [
            insight_one_id,
            insight_three_id,
            insight_four_id,
        ]

    def test_cannot_update_an_insight_if_on_restricted_dashboard(self) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        insight_id, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk],
            }
        )
        assert [t["dashboard_id"] for t in response_data["dashboard_tiles"]] == [dashboard_restricted.pk]

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"name": "changing when restricted"},
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_admin_user_cannot_add_an_insight_to_a_restricted_dashboard(
        self,
    ) -> None:
        # create insight and dashboard separately with default user
        dashboard_restricted_id, _ = self.dashboard_api.create_dashboard(
            {"restriction_level": Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT}
        )

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        # user with no permissions on the dashboard cannot add insight to it
        user_without_permissions = User.objects.create_and_join(
            organization=self.organization,
            email="no_access_user@posthog.com",
            password=None,
        )
        self.client.force_login(user_without_permissions)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted_id]},
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        self.client.force_login(self.user)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted_id]},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_admin_user_can_add_an_insight_to_a_restricted_dashboard(self) -> None:
        # create insight and dashboard separately with default user
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        insight_id, response_data = self.dashboard_api.create_insight(data={"name": "starts un-restricted dashboard"})

        # an admin user has implicit permissions on the dashboard and can add the insight to it
        admin = User.objects.create_and_join(
            organization=self.organization,
            email="team2@posthog.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/insights/{insight_id}",
            {"dashboards": [dashboard_restricted.id]},
        )
        assert response.status_code == status.HTTP_200_OK

    def test_an_insight_on_no_dashboard_has_no_restrictions(self) -> None:
        _, response_data = self.dashboard_api.create_insight(data={"name": "not on a dashboard"})
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_unrestricted_dashboard_has_no_restrictions(self) -> None:
        dashboard: Dashboard = Dashboard.objects.create(team=self.team)
        _, response_data = self.dashboard_api.create_insight(
            data={"name": "on an unrestricted dashboard", "dashboards": [dashboard.pk]}
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_restricted_dashboard_has_restrictions_cannot_edit_without_explicit_privilege(
        self,
    ) -> None:
        dashboard: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        _, response_data = self.dashboard_api.create_insight(
            data={"name": "on a restricted dashboard", "dashboards": [dashboard.pk]}
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_VIEW,
        )

    def test_an_insight_on_both_restricted_and_unrestricted_dashboard_has_no_restrictions(
        self,
    ) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        dashboard_unrestricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.EVERYONE_IN_PROJECT_CAN_EDIT,
        )
        _, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk, dashboard_unrestricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

    def test_an_insight_on_restricted_dashboard_does_not_restrict_admin(self) -> None:
        dashboard_restricted: Dashboard = Dashboard.objects.create(
            team=self.team,
            restriction_level=Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )

        admin = User.objects.create_and_join(
            organization=self.organization,
            email="y@x.com",
            password=None,
            level=OrganizationMembership.Level.ADMIN,
        )
        self.client.force_login(admin)
        _, response_data = self.dashboard_api.create_insight(
            data={
                "name": "on a restricted and unrestricted dashboard",
                "dashboards": [dashboard_restricted.pk],
            }
        )
        self.assertEqual(
            response_data["effective_restriction_level"],
            Dashboard.RestrictionLevel.ONLY_COLLABORATORS_CAN_EDIT,
        )
        self.assertEqual(
            response_data["effective_privilege_level"],
            Dashboard.PrivilegeLevel.CAN_EDIT,
        )

        # :KLUDGE: avoid making extra queries that are explicitly not cached in tests. Avoids false N+1-s.
        @override_settings(PERSON_ON_EVENTS_OVERRIDE=False, PERSON_ON_EVENTS_V2_OVERRIDE=False)
        @snapshot_postgres_queries
        def test_listing_insights_does_not_nplus1(self) -> None:
            query_counts: list[int] = []
            queries = []

            for i in range(5):
                user = User.objects.create(email=f"testuser{i}@posthog.com")
                OrganizationMembership.objects.create(user=user, organization=self.organization)
                dashboard = Dashboard.objects.create(name=f"Dashboard {i}", team=self.team)

                self.dashboard_api.create_insight(
                    data={
                        "short_id": f"insight{i}",
                        "dashboards": [dashboard.pk],
                        "filters": {"events": [{"id": "$pageview"}]},
                    }
                )

                self.assertEqual(Insight.objects.count(), i + 1)

                with capture_db_queries() as capture_query_context:
                    response = self.client.get(f"/api/projects/{self.team.id}/insights?basic=true")
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    self.assertEqual(len(response.json()["results"]), i + 1)

                query_count_for_create_and_read = len(capture_query_context.captured_queries)
                queries.append(capture_query_context.captured_queries)
                query_counts.append(query_count_for_create_and_read)

            # adding more insights doesn't change the query count
            self.assertEqual(
                [
                    FuzzyInt(11, 12),
                    FuzzyInt(11, 12),
                    FuzzyInt(11, 12),
                    FuzzyInt(11, 12),
                    FuzzyInt(11, 12),
                ],
                query_counts,
                f"received query counts\n\n{query_counts}",
            )

    def assert_insight_activity(self, insight_id: Optional[int], expected: list[dict]):
        activity_response = self.dashboard_api.get_insight_activity(insight_id)

        activity: list[dict] = activity_response["results"]

        self.maxDiff = None
        assert activity == expected
