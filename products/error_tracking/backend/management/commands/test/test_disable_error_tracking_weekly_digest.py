from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

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
        assert settings1["error_tracking_weekly_digest"] is False
        assert settings2["error_tracking_weekly_digest"] is False

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
