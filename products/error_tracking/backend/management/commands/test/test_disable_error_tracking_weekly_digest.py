from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models import Team
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.user import User


class TestDisableErrorTrackingWeeklyDigest(BaseTest):
    def test_disables_for_single_email(self):
        out = StringIO()
        call_command("disable_error_tracking_weekly_digest", "--email", self.user.email, stdout=out)

        self.user.refresh_from_db()
        settings = self.user.partial_notification_settings or {}
        assert settings["error_tracking_weekly_digest"] is False
        assert "Updated 1 user(s)" in out.getvalue()

    def test_disables_for_multiple_emails(self):
        user2 = User.objects.create_user(
            email="test2@example.com",
            password="testpassword",
            first_name="Test2",
        )

        out = StringIO()
        call_command(
            "disable_error_tracking_weekly_digest",
            "--email",
            self.user.email,
            "--email",
            user2.email,
            stdout=out,
        )

        self.user.refresh_from_db()
        user2.refresh_from_db()
        settings1 = self.user.partial_notification_settings or {}
        settings2 = user2.partial_notification_settings or {}
        assert settings1["error_tracking_weekly_digest"] is False
        assert settings2["error_tracking_weekly_digest"] is False
        assert "Updated 2 user(s)" in out.getvalue()

    def test_disables_for_organization(self):
        user2 = User.objects.create_user(
            email="test2@example.com",
            password="testpassword",
            first_name="Test2",
        )
        user2.join(organization=self.organization, level=OrganizationMembership.Level.MEMBER)

        out = StringIO()
        call_command(
            "disable_error_tracking_weekly_digest",
            "--organization-id",
            str(self.organization.id),
            stdout=out,
        )

        self.user.refresh_from_db()
        user2.refresh_from_db()
        settings1 = self.user.partial_notification_settings or {}
        settings2 = user2.partial_notification_settings or {}
        assert "error_tracking_weekly_digest" not in settings1
        assert "error_tracking_weekly_digest" not in settings2
        assert settings1["error_tracking_weekly_digest_project_enabled"][str(self.team.id)] is False
        assert settings2["error_tracking_weekly_digest_project_enabled"][str(self.team.id)] is False

    def test_dry_run_does_not_modify(self):
        out = StringIO()
        call_command("disable_error_tracking_weekly_digest", "--email", self.user.email, "--dry-run", stdout=out)

        self.user.refresh_from_db()
        settings = self.user.partial_notification_settings or {}
        assert settings.get("error_tracking_weekly_digest") is not False
        assert "Dry run" in out.getvalue()
        assert "Would disable" in out.getvalue()

    def test_skips_already_disabled(self):
        self.user.partial_notification_settings = {"error_tracking_weekly_digest": False}
        self.user.save()

        out = StringIO()
        call_command("disable_error_tracking_weekly_digest", "--email", self.user.email, stdout=out)

        assert "already disabled" in out.getvalue()
        assert "Updated 0 user(s), 1 already disabled" in out.getvalue()

    def test_requires_email_or_organization(self):
        err = StringIO()
        call_command("disable_error_tracking_weekly_digest", stderr=err)
        assert "Must provide at least one --email or --organization-id" in err.getvalue()

    def test_handles_nonexistent_email(self):
        out = StringIO()
        call_command("disable_error_tracking_weekly_digest", "--email", "nobody@example.com", stdout=out)
        assert "No matching users found" in out.getvalue()

    def test_handles_empty_organization(self):
        empty_org = Organization.objects.create(name="Empty Org")

        out = StringIO()
        call_command("disable_error_tracking_weekly_digest", "--organization-id", str(empty_org.id), stdout=out)
        assert "No matching users found" in out.getvalue()

    def test_organization_scope_does_not_touch_global_or_other_orgs(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        self.user.join(organization=other_org, level=OrganizationMembership.Level.MEMBER)

        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {
                str(other_team.id): True,
            },
        }
        self.user.save()

        call_command(
            "disable_error_tracking_weekly_digest",
            "--organization-id",
            str(self.organization.id),
            stdout=StringIO(),
        )

        self.user.refresh_from_db()
        settings = self.user.partial_notification_settings or {}
        assert "error_tracking_weekly_digest" not in settings
        project_map = settings["error_tracking_weekly_digest_project_enabled"]
        assert project_map[str(self.team.id)] is False
        assert project_map[str(other_team.id)] is True

    def test_email_and_organization_overlap_uses_per_project(self):
        # User matched by both --email and --organization-id should get per-project treatment.
        call_command(
            "disable_error_tracking_weekly_digest",
            "--email",
            self.user.email,
            "--organization-id",
            str(self.organization.id),
            stdout=StringIO(),
        )

        self.user.refresh_from_db()
        settings = self.user.partial_notification_settings or {}
        assert "error_tracking_weekly_digest" not in settings
        assert settings["error_tracking_weekly_digest_project_enabled"][str(self.team.id)] is False

    def test_email_only_user_still_globally_disabled_when_org_also_provided(self):
        # User matched only by --email (not in org) should still get the global flag set.
        outside_user = User.objects.create_user(
            email="outside@example.com",
            password="testpassword",
            first_name="Outside",
        )

        call_command(
            "disable_error_tracking_weekly_digest",
            "--email",
            outside_user.email,
            "--organization-id",
            str(self.organization.id),
            stdout=StringIO(),
        )

        outside_user.refresh_from_db()
        settings = outside_user.partial_notification_settings or {}
        assert settings["error_tracking_weekly_digest"] is False
        assert "error_tracking_weekly_digest_project_enabled" not in settings

    def test_organization_skips_when_all_org_teams_already_disabled(self):
        self.user.partial_notification_settings = {
            "error_tracking_weekly_digest_project_enabled": {str(self.team.id): False},
        }
        self.user.save()

        out = StringIO()
        call_command(
            "disable_error_tracking_weekly_digest",
            "--organization-id",
            str(self.organization.id),
            stdout=out,
        )
        assert "already disabled for org's projects" in out.getvalue()
        assert "Updated 0 user(s), 1 already disabled" in out.getvalue()

    def test_preserves_other_notification_settings(self):
        self.user.partial_notification_settings = {
            "plugin_disabled": True,
            "discussions_mentioned": True,
        }
        self.user.save()

        call_command("disable_error_tracking_weekly_digest", "--email", self.user.email, stdout=StringIO())

        self.user.refresh_from_db()
        settings = self.user.partial_notification_settings or {}
        assert settings["error_tracking_weekly_digest"] is False
        assert settings["plugin_disabled"] is True
        assert settings["discussions_mentioned"] is True
