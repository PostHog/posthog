import datetime as dt

from freezegun.api import freeze_time
from unittest import mock
from unittest.mock import ANY, call, patch

from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.organization import Organization, OrganizationMembership
from posthog.tasks.tasks import sync_all_organization_available_product_features

from products.enterprise.backend.api.test.base import APILicensedTest
from products.enterprise.backend.models.license import License
from products.enterprise.backend.models.rbac.access_control import AccessControl


class TestOrganizationEnterpriseAPI(APILicensedTest):
    def test_create_organization(self):
        response = self.client.post("/api/organizations/", {"name": "Test"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Organization.objects.count(), 2)
        response_data = response.json()
        self.assertEqual(response_data.get("name"), "Test")
        self.assertEqual(
            OrganizationMembership.objects.filter(organization_id=response_data.get("id")).count(),
            1,
        )
        self.assertEqual(
            OrganizationMembership.objects.get(organization_id=response_data.get("id"), user=self.user).level,
            OrganizationMembership.Level.OWNER,
        )

    @patch("posthog.models.utils.generate_random_short_suffix", return_value="YYYY")
    def test_create_two_similarly_named_organizations(self, mock_choice):
        response = self.client.post(
            "/api/organizations/",
            {"name": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertLessEqual(
            {
                "name": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                "slug": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            }.items(),
            response.json().items(),
        )

        response = self.client.post(
            "/api/organizations/",
            {"name": "#XXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxX"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertLessEqual(
            {
                "name": "#XXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxX",
                "slug": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-YYYY",
            }.items(),
            response.json().items(),
        )

    @patch("posthog.api.organization.delete_bulky_postgres_data")
    @patch("posthoganalytics.capture")
    def test_delete_second_managed_organization(self, mock_capture, mock_delete_bulky_postgres_data):
        organization, _, team = Organization.objects.bootstrap(self.user, name="X")
        organization_props = organization.get_analytics_metadata()
        self.assertTrue(Organization.objects.filter(id=organization.id).exists())
        self.assertTrue(Team.objects.filter(id=team.id).exists())
        response = self.client.delete(f"/api/organizations/{organization.id}")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Organization.objects.filter(id=organization.id).exists())
        self.assertFalse(Team.objects.filter(id=team.id).exists())

        mock_capture.assert_called_once_with(
            event="organization deleted",
            distinct_id=self.user.distinct_id,
            properties=organization_props,
            groups={"instance": ANY, "organization": str(organization.id)},
        )
        mock_delete_bulky_postgres_data.assert_called_once_with(team_ids=[team.id])

    @patch("posthoganalytics.capture")
    def test_delete_last_organization(self, mock_capture):
        org_id = self.organization.id
        organization_props = self.organization.get_analytics_metadata()
        self.assertTrue(Organization.objects.filter(id=org_id).exists())

        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()

        response = self.client.delete(f"/api/organizations/{org_id}")

        self.assertEqual(
            response.status_code,
            204,
            "Did not successfully delete last organization on the instance",
        )
        self.assertFalse(Organization.objects.filter(id=org_id).exists())
        self.assertFalse(Organization.objects.exists())

        response_bis = self.client.delete(f"/api/organizations/{org_id}")

        self.assertEqual(
            response_bis.status_code,
            404,
            "Did not return a 404 on trying to delete a nonexistent org",
        )

        mock_capture.assert_has_calls(
            [
                call(
                    distinct_id=self.user.distinct_id,
                    event="membership level changed",
                    properties={"new_level": 15, "previous_level": 1, "$set": mock.ANY},
                    groups=mock.ANY,
                ),
                call(
                    distinct_id=self.user.distinct_id,
                    event="organization deleted",
                    properties=organization_props,
                    groups={"instance": mock.ANY, "organization": str(org_id)},
                ),
            ]
        )

    def test_no_delete_organization_not_owning(self):
        for level in (
            OrganizationMembership.Level.MEMBER,
            OrganizationMembership.Level.ADMIN,
        ):
            self.organization_membership.level = level
            self.organization_membership.save()
            response = self.client.delete(f"/api/organizations/{self.organization.id}")
            potential_err_message = f"Somehow managed to delete the org as a level {level} (which is not owner)"
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "detail": "You do not have admin access to this resource."
                    if level == OrganizationMembership.Level.MEMBER
                    else "Your organization access level is insufficient.",
                    "code": "permission_denied",
                    "type": "authentication_error",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 403, potential_err_message)
            self.assertTrue(self.organization.name, self.CONFIG_ORGANIZATION_NAME)

    def test_delete_organization_owning(self):
        self.organization_membership.level = OrganizationMembership.Level.OWNER
        self.organization_membership.save()
        membership_ids = OrganizationMembership.objects.filter(organization=self.organization).values_list(
            "id", flat=True
        )

        response = self.client.delete(f"/api/organizations/{self.organization.id}")

        potential_err_message = f"Somehow did not delete the org as the owner"
        self.assertEqual(response.status_code, 204, potential_err_message)
        self.assertFalse(
            Organization.objects.filter(id=self.organization.id).exists(),
            potential_err_message,
        )
        self.assertFalse(OrganizationMembership.objects.filter(id__in=membership_ids).exists())
        self.assertTrue(User.objects.filter(id=self.user.pk).exists())

    def test_no_delete_organization_not_belonging_to(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            organization = Organization.objects.create(name="Some Other Org")
            response = self.client.delete(f"/api/organizations/{organization.id}")
            potential_err_message = f"Somehow managed to delete someone else's org as a level {level} in own org"
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "detail": "Not found.",
                    "code": "not_found",
                    "type": "invalid_request",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 404, potential_err_message)
            self.assertTrue(
                Organization.objects.filter(id=organization.id).exists(),
                potential_err_message,
            )

    def test_update_org(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            response_rename = self.client.patch(f"/api/organizations/{self.organization.id}", {"name": "Woof"})
            response_email = self.client.patch(
                f"/api/organizations/{self.organization.id}",
                {"is_member_join_email_enabled": False},
            )
            self.organization.refresh_from_db()

            expected_response = {
                "attr": None,
                "detail": "Your organization access level is insufficient.",
                "code": "permission_denied",
                "type": "authentication_error",
            }
            if level < OrganizationMembership.Level.ADMIN:
                potential_err_message = f"Somehow managed to update the org as a level {level} (which is below admin)"
                self.assertEqual(response_rename.json(), expected_response, potential_err_message)
                self.assertEqual(response_rename.status_code, 403, potential_err_message)
                self.assertTrue(self.organization.name, self.CONFIG_ORGANIZATION_NAME)
                self.assertEqual(response_email.json(), expected_response, potential_err_message)
                self.assertEqual(response_email.status_code, 403, potential_err_message)
            else:
                potential_err_message = f"Somehow did not update the org as a level {level} (which is at least admin)"
                self.assertEqual(response_rename.status_code, 200, potential_err_message)
                self.assertEqual(response_email.status_code, 200, potential_err_message)
                self.assertTrue(self.organization.name, "Woof")

    def test_no_update_organization_not_belonging_to(self):
        for level in OrganizationMembership.Level:
            self.organization_membership.level = level
            self.organization_membership.save()
            organization = Organization.objects.create(name="Meow")
            response = self.client.patch(f"/api/organizations/{organization.id}", {"name": "Mooooooooo"})
            potential_err_message = f"Somehow managed to update someone else's org as a level {level} in own org"
            self.assertEqual(
                response.json(),
                {
                    "attr": None,
                    "detail": "Not found.",
                    "code": "not_found",
                    "type": "invalid_request",
                },
                potential_err_message,
            )
            self.assertEqual(response.status_code, 404, potential_err_message)
            organization.refresh_from_db()
            self.assertTrue(organization.name, "Meow")

    def test_feature_available_self_hosted_has_license(self):
        current_plans = License.PLANS
        License.PLANS = {"enterprise": ["whatever"]}  # type: ignore
        with self.is_cloud(False):
            License.objects.create(
                key="key",
                plan="enterprise",
                valid_until=dt.datetime.now() + dt.timedelta(days=1),
            )

            # Still only old, empty available_product_features field value known
            self.assertIsNone(self.organization.get_available_feature("whatever"))
            self.assertFalse(self.organization.is_feature_available("whatever"))
            self.assertIsNone(self.organization.get_available_feature("feature-doesnt-exist"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))

            # New available_product_features field value that was updated in DB on license creation is known after refresh
            self.organization.refresh_from_db()
            self.assertEqual(
                {"key": "whatever", "name": "Whatever"}, self.organization.get_available_feature("whatever")
            )
            self.assertTrue(self.organization.is_feature_available("whatever"))
            self.assertFalse(self.organization.get_available_feature("feature-doesnt-exist"))
            self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))
        License.PLANS = current_plans

    def test_feature_available_self_hosted_no_license(self):
        current_plans = License.PLANS
        License.PLANS = {"enterprise": ["whatever"]}  # type: ignore

        self.assertIsNone(self.organization.get_available_feature("whatever"))
        self.assertFalse(self.organization.is_feature_available("whatever"))
        self.assertIsNone(self.organization.get_available_feature("feature-doesnt-exist"))
        self.assertFalse(self.organization.is_feature_available("feature-doesnt-exist"))
        License.PLANS = current_plans

    @patch("ee.api.license.requests.post")
    def test_feature_available_self_hosted_license_expired(self, patch_post):
        current_plans = License.PLANS
        License.PLANS = {"enterprise": ["whatever"]}  # type: ignore

        with freeze_time("2070-01-01T12:00:00.000Z"):  # LicensedTestMixin enterprise license expires in 2038
            sync_all_organization_available_product_features()  # This is normally ran every hour
            self.organization.refresh_from_db()
            self.assertIsNone(self.organization.get_available_feature("whatever"))
            self.assertFalse(self.organization.is_feature_available("whatever"))
        License.PLANS = current_plans

    def test_get_organization_restricted_teams_hidden(self):
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        forbidden_team = Team.objects.create(
            organization=self.organization,
            name="FORBIDDEN",
        )

        # Set up new access control system - restrict project to no default access
        AccessControl.objects.create(
            team=forbidden_team,
            access_level="none",
            resource="project",
            resource_id=str(forbidden_team.id),
        )

        response = self.client.get(f"/api/organizations/{self.organization.id}")

        self.assertEqual(response.status_code, 200)
        self.assertListEqual(
            [team["name"] for team in response.json()["teams"]],
            [self.team.name],  # "FORBIDDEN" excluded
        )

    def test_member_cannot_update_members_can_invite_on_org(self):
        """Test that members cannot update members_can_invite when ORGANIZATION_INVITE_SETTINGS is available."""
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        # Enable ORGANIZATION_INVITE_SETTINGS feature
        self.organization.available_product_features = [{"key": AvailableFeature.ORGANIZATION_INVITE_SETTINGS}]
        self.organization.save()

        response = self.client.patch(f"/api/organizations/{self.organization.id}", {"members_can_invite": True})
        self.assertEqual(response.status_code, 403)

    @patch("posthog.tasks.tasks.environments_rollback_migration.delay")
    def test_environments_rollback_success(self, mock_task_delay):
        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {
                str(staging_env.id): production_env.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"success": True, "message": "Migration started"})

        mock_task_delay.assert_called_once_with(
            organization_id=self.organization.id,
            environment_mappings={str(staging_env.id): production_env.id},
            user_id=self.user.id,
        )

    def test_environments_rollback_empty_mappings(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "attr": None,
                "code": "invalid_input",
                "detail": "Environment mappings are required",
                "type": "validation_error",
            },
        )

    def test_environments_rollback_invalid_environments(self):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        nonexistent_source_id = "999999"
        nonexistent_target_id = 888888
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {nonexistent_source_id: nonexistent_target_id},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "attr": None,
                "code": "invalid_input",
                "detail": "Environments not found: {888888, 999999}",
                "type": "validation_error",
            },
        )

    def test_environments_rollback_permission_denied(self):
        project_2 = Team.objects.create(organization=self.organization, name="Project 2")
        env_2 = Team.objects.create(organization=self.organization, name="Env 2", project_id=project_2.id)

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {str(project_2.id): env_2.id},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "You do not have admin access to this resource.")

    def test_environments_rollback_wrong_organization(self):
        other_org = Organization.objects.create(name="Other Org")
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{other_org.id}/environments_rollback/",
            {"1": 1},
            format="json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "Not found.")

    @patch("posthog.tasks.tasks.environments_rollback_migration.delay")
    def test_environments_rollback_multiple_mappings(self, mock_task_delay):
        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)
        dev_env = Team.objects.create(organization=self.organization, name="Dev", project_id=main_project.id)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {
                str(staging_env.id): production_env.id,
                str(dev_env.id): production_env.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"success": True, "message": "Migration started"})

        mock_task_delay.assert_called_once_with(
            organization_id=self.organization.id,
            environment_mappings={
                str(staging_env.id): production_env.id,
                str(dev_env.id): production_env.id,
            },
            user_id=self.user.id,
        )

    @patch("posthog.tasks.tasks.environments_rollback_migration.delay")
    def test_environments_rollback_data_format_conversion(self, mock_task_delay):
        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {
                staging_env.id: str(production_env.id),
                str(production_env.id): production_env.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"success": True, "message": "Migration started"})

        mock_task_delay.assert_called_once_with(
            organization_id=self.organization.id,
            environment_mappings={
                str(staging_env.id): production_env.id,
                str(production_env.id): production_env.id,
            },
            user_id=self.user.id,
        )

    @patch("posthog.tasks.tasks.environments_rollback_migration.delay")
    def test_environments_rollback_validates_environments_exist(self, mock_task_delay):
        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        nonexistent_source_id = "99999"
        nonexistent_target_id = "88888"
        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {
                nonexistent_source_id: production_env.id,
                str(production_env.id): nonexistent_target_id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Environments not found", response.json()["detail"])
        mock_task_delay.assert_not_called()

    def test_organization_api_includes_default_role_id(self):
        """Test that the organization API includes the default_role_id field"""
        from products.enterprise.backend.models import Role

        # Create a role and set it as default
        role = Role.objects.create(name="Default Role", organization=self.organization)
        self.organization.default_role_id = role.id
        self.organization.save()

        response = self.client.get(f"/api/organizations/{self.organization.id}/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("default_role_id", data)
        self.assertEqual(data["default_role_id"], str(role.id))

    def test_set_default_role_via_api(self):
        """Test that the default role can be set via the organization API"""
        from products.enterprise.backend.models import Role

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a role
        role = Role.objects.create(name="API Default Role", organization=self.organization)

        response = self.client.patch(f"/api/organizations/{self.organization.id}/", {"default_role_id": str(role.id)})

        self.assertEqual(response.status_code, 200)

        # Check that it was set
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.default_role_id, role.id)

    def test_clear_default_role_via_api(self):
        """Test that the default role can be cleared via the organization API"""
        from products.enterprise.backend.models import Role

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        # Create a role and set it as default
        role = Role.objects.create(name="To Be Cleared", organization=self.organization)
        self.organization.default_role_id = role.id
        self.organization.save()

        response = self.client.patch(f"/api/organizations/{self.organization.id}/", {"default_role_id": None})

        self.assertEqual(response.status_code, 200)

        # Check that it was cleared
        self.organization.refresh_from_db()
        self.assertIsNone(self.organization.default_role_id)

    def test_role_serializer_includes_is_default_field(self):
        """Test that the role serializer includes is_default field"""
        from products.enterprise.backend.models import Role

        # Create a role and set it as default
        role = Role.objects.create(name="Default Role", organization=self.organization)
        self.organization.default_role_id = role.id
        self.organization.save()

        response = self.client.get(f"/api/organizations/{self.organization.id}/roles/")

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Find our role in the results
        default_role = next(r for r in data["results"] if r["id"] == str(role.id))
        self.assertTrue(default_role["is_default"])

    @patch("posthog.tasks.tasks.environments_rollback_migration.delay")
    def test_environments_rollback_validates_environments_belong_to_organization(self, mock_task_delay):
        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        our_production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )

        other_organization = Organization.objects.create(name="Other Organization")
        other_project = Team.objects.create(organization=other_organization, name="Other Project")
        other_env = Team.objects.create(organization=other_organization, name="Other Env", project_id=other_project.id)

        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {
                str(other_env.id): our_production_env.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Environments not found", response.json()["detail"])
        mock_task_delay.assert_not_called()

    @patch("posthog.tasks.tasks.environments_rollback_migration.delay")
    def test_environments_rollback_requires_admin_permission(self, mock_task_delay):
        main_project = Team.objects.create(organization=self.organization, name="Main Project")
        production_env = Team.objects.create(
            organization=self.organization, name="Production", project_id=main_project.id
        )
        staging_env = Team.objects.create(organization=self.organization, name="Staging", project_id=main_project.id)

        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()

        response = self.client.post(
            f"/api/organizations/{self.organization.id}/environments_rollback/",
            {str(staging_env.id): production_env.id},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "You do not have admin access to this resource.")
        mock_task_delay.assert_not_called()
