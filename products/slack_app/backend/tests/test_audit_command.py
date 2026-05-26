from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey, find_personal_api_key
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value

from products.slack_app.backend.audit_command import (
    AUDIT_KEY_TTL,
    AuditCommandError,
    dispatch_audit_run,
    mint_ephemeral_audit_key,
)


class TestMintEphemeralAuditKey(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Production")
        self.staff_user = User.objects.create(email="staff@posthog.com", first_name="Staff", is_staff=True)

    def test_key_is_scoped_to_one_team_with_ttl_and_read_only_scopes(self) -> None:
        before = timezone.now()
        key, raw_token = mint_ephemeral_audit_key(
            team=self.team, staff_user=self.staff_user, skill="auditing-experiments-flags"
        )
        after = timezone.now()

        assert key.user_id == self.staff_user.id
        assert key.scoped_teams == [self.team.id]
        # Read-only: no *:write scope leaked through and no `*` wildcard which
        # short-circuits the scope check in permissions.py.
        assert "*" not in key.scopes
        assert all(scope.endswith(":read") for scope in key.scopes)
        # TTL window — `expires_at` is `now + AUDIT_KEY_TTL` modulo whatever
        # time passed between setUp and the assertion.
        assert key.expires_at is not None
        assert before + AUDIT_KEY_TTL - timedelta(seconds=5) <= key.expires_at
        assert key.expires_at <= after + AUDIT_KEY_TTL + timedelta(seconds=5)
        # `raw_token` is the plaintext value handed to the agent. The DB only
        # stores the hash; the raw value must never be findable on the row.
        assert raw_token
        assert key.secure_value
        assert raw_token != key.secure_value
        # Sanity check that the stored hash actually validates against the raw.
        refetched = PersonalAPIKey.objects.get(pk=key.pk)
        assert refetched.mask_value and refetched.mask_value.startswith("phx_")

    def test_expired_key_is_rejected_by_find_personal_api_key(self) -> None:
        key, raw_token = mint_ephemeral_audit_key(
            team=self.team, staff_user=self.staff_user, skill="auditing-experiments-flags"
        )
        assert find_personal_api_key(raw_token) is not None

        key.expires_at = timezone.now() - timedelta(seconds=1)
        key.save(update_fields=["expires_at"])
        assert find_personal_api_key(raw_token) is None

    def test_user_facing_keys_with_null_expires_at_still_validate(self) -> None:
        raw_token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            user=self.staff_user,
            label="normal user key",
            secure_value=hash_key_value(raw_token),
            mask_value=mask_key_value(raw_token),
            scopes=["query:read"],
            # expires_at intentionally omitted — keys minted via the public API
            # should remain valid forever (until the user revokes them).
        )
        result = find_personal_api_key(raw_token)
        assert result is not None
        found_key, _mode = result
        assert found_key.expires_at is None


class TestDispatchAuditRun(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Production")
        self.staff_user = User.objects.create(email="staff@posthog.com", first_name="Staff", is_staff=True)
        self.non_staff_user = User.objects.create(email="customer@example.com", first_name="Customer", is_staff=False)

    def test_writes_activity_log_and_mints_key_for_staff(self) -> None:
        before = ActivityLog.objects.count()
        result = dispatch_audit_run(team=self.team, staff_user=self.staff_user, skill="auditing-experiments-flags")

        assert ActivityLog.objects.count() == before + 1
        entry = ActivityLog.objects.latest("created_at")
        assert entry.scope == "Team"
        assert entry.team_id == self.team.id
        assert entry.organization_id == self.organization.id
        assert entry.activity == "external_audit_started"
        assert entry.user_id == self.staff_user.id
        assert entry.was_impersonated is False
        detail = entry.detail
        assert detail is not None
        assert detail["type"] == "auditing-experiments-flags"

        assert result.api_key.scoped_teams == [self.team.id]
        assert result.raw_token

    def test_rejects_non_staff_user_and_does_not_log_or_mint(self) -> None:
        before_logs = ActivityLog.objects.count()
        before_keys = PersonalAPIKey.objects.count()

        with self.assertRaises(AuditCommandError) as cm:
            dispatch_audit_run(team=self.team, staff_user=self.non_staff_user, skill="auditing-experiments-flags")
        assert "restricted to staff" in str(cm.exception)

        assert ActivityLog.objects.count() == before_logs
        assert PersonalAPIKey.objects.count() == before_keys

    def test_rejects_skill_outside_allowlist_and_does_not_log_or_mint(self) -> None:
        before_logs = ActivityLog.objects.count()
        before_keys = PersonalAPIKey.objects.count()

        with self.assertRaises(AuditCommandError) as cm:
            dispatch_audit_run(team=self.team, staff_user=self.staff_user, skill="write-everything-skill")
        assert "isn't an allowed audit skill" in str(cm.exception)

        assert ActivityLog.objects.count() == before_logs
        assert PersonalAPIKey.objects.count() == before_keys


class TestPhAuditManagementCommand(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Acme")
        self.team = Team.objects.create(organization=self.organization, name="Acme Production")
        self.staff_user = User.objects.create(email="staff@posthog.com", first_name="Staff", is_staff=True)
        self.non_staff_user = User.objects.create(email="customer@example.com", first_name="Customer", is_staff=False)

    def _run(self, *, project_id: int, skill: str, staff_email: str) -> str:
        stdout = StringIO()
        call_command(
            "ph_audit",
            f"--project-id={project_id}",
            f"--skill={skill}",
            f"--staff-email={staff_email}",
            stdout=stdout,
        )
        return stdout.getvalue()

    def test_happy_path_writes_activity_log_and_prints_summary(self) -> None:
        before = ActivityLog.objects.count()
        output = self._run(
            project_id=self.team.id,
            skill="auditing-experiments-flags",
            staff_email=self.staff_user.email,
        )
        assert ActivityLog.objects.count() == before + 1
        entry = ActivityLog.objects.latest("created_at")
        assert entry.activity == "external_audit_started"
        assert entry.user_id == self.staff_user.id

        assert "auditing-experiments-flags" in output
        assert self.team.name in output
        assert self.organization.name in output
        # Raw token must NOT be printed — only the key id and expiry.
        assert "Ephemeral key id:" in output

    def test_happy_path_does_not_leak_raw_token(self) -> None:
        output = self._run(
            project_id=self.team.id,
            skill="auditing-experiments-flags",
            staff_email=self.staff_user.email,
        )
        # `generate_random_token_personal` produces tokens with a "phx_" prefix.
        # Even one such substring in the management-command output would be a leak.
        assert "phx_" not in output

    @parameterized.expand(
        [
            (
                "non_staff_user",
                lambda self: {
                    "project_id": self.team.id,
                    "skill": "auditing-experiments-flags",
                    "staff_email": self.non_staff_user.email,
                },
                "restricted to staff",
            ),
            (
                "unknown_user",
                lambda self: {
                    "project_id": self.team.id,
                    "skill": "auditing-experiments-flags",
                    "staff_email": "nobody@posthog.com",
                },
                "No PostHog user found",
            ),
            (
                "missing_project",
                lambda self: {
                    "project_id": 999_999_999,
                    "skill": "auditing-experiments-flags",
                    "staff_email": "staff@posthog.com",
                },
                "not found",
            ),
            (
                "disallowed_skill",
                lambda self: {
                    "project_id": self.team.id,
                    "skill": "write-everything-skill",
                    "staff_email": "staff@posthog.com",
                },
                "isn't an allowed audit skill",
            ),
        ]
    )
    def test_command_error_paths(self, _name: str, kwargs_fn, expected_message: str) -> None:
        before_logs = ActivityLog.objects.count()
        before_keys = PersonalAPIKey.objects.count()

        with self.assertRaises(CommandError) as cm:
            self._run(**kwargs_fn(self))
        assert expected_message in str(cm.exception)

        # Error paths must never mutate audit state.
        assert ActivityLog.objects.count() == before_logs
        assert PersonalAPIKey.objects.count() == before_keys
