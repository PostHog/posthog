import time
from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings as django_settings
from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.logs.backend.models import LogsSigningSecret


class TestLogsSigningSecretAPI(APIBaseTest):
    def _url(self, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/logs/signing_secret/{suffix}"

    def _make_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_get_without_a_row_returns_null(self):
        response = self.client.get(self._url())
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"secret": None, "updated_at": None, "previous_secret_valid_until": None}

    def test_first_rotate_creates_the_secret_with_no_grace_period(self):
        self._make_admin()

        response = self.client.post(self._url("rotate/"))

        assert response.status_code == status.HTTP_200_OK
        row = LogsSigningSecret.objects.for_team(self.team.id).get()
        assert response.json()["secret"] == row.secret
        assert response.json()["previous_secret_valid_until"] is None
        assert self.client.get(self._url()).json()["secret"] == row.secret

    def test_rotate_keeps_the_old_secret_for_the_grace_period_and_masks_the_audit_entry(self):
        self._make_admin()
        LogsSigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="old_secret_value")

        response = self.client.post(self._url("rotate/"))

        assert response.status_code == status.HTTP_200_OK
        row = LogsSigningSecret.objects.for_team(self.team.id).get()
        assert row.secret != "old_secret_value"
        assert row.previous_secret == "old_secret_value"
        assert row.previous_secret_active
        assert response.json()["previous_secret_valid_until"] is not None

        log = ActivityLog.objects.get(
            scope="Team", team_id=self.team.id, detail__changes__0__field="logs_signing_secret"
        )
        assert log.user == self.user
        assert row.secret not in str(log.detail)
        assert "old_secret_value" not in str(log.detail)

    def test_previous_secret_expires_after_the_grace_period(self):
        LogsSigningSecret.objects.for_team(self.team.id).create(
            team=self.team,
            secret="new_secret_value",
            previous_secret="old_secret_value",
            previous_secret_rotated_at=timezone.now() - LogsSigningSecret.PREVIOUS_SECRET_GRACE - timedelta(seconds=1),
        )

        response = self.client.get(self._url())

        assert response.json()["previous_secret_valid_until"] is None
        assert not LogsSigningSecret.objects.for_team(self.team.id).get().previous_secret_active

    def test_expire_previous_ends_the_grace_period(self):
        self._make_admin()
        LogsSigningSecret.objects.for_team(self.team.id).create(
            team=self.team,
            secret="new_secret_value",
            previous_secret="old_secret_value",
            previous_secret_rotated_at=timezone.now(),
        )

        response = self.client.post(self._url("expire_previous/"))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["previous_secret_valid_until"] is None
        assert LogsSigningSecret.objects.for_team(self.team.id).get().previous_secret is None
        log = ActivityLog.objects.get(
            scope="Team", team_id=self.team.id, detail__changes__0__field="logs_signing_secret_previous"
        )
        assert "old_secret_value" not in str(log.detail)

    def test_rotate_requires_admin(self):
        response = self.client.post(self._url("rotate/"))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not LogsSigningSecret.objects.for_team(self.team.id).exists()

    def test_member_without_logs_access_cannot_read_the_secret(self):
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        AccessControl.objects.create(resource="logs", team=self.team, access_level="none")
        LogsSigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="secret_value")

        response = self.client.get(self._url())

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_rotate_rolls_back_when_the_audit_entry_fails(self):
        self._make_admin()
        LogsSigningSecret.objects.for_team(self.team.id).create(team=self.team, secret="old_secret_value")

        with patch.object(ActivityLog.objects, "create", side_effect=RuntimeError("audit write failed")):
            with self.assertRaises(RuntimeError):
                self.client.post(self._url("rotate/"))

        assert LogsSigningSecret.objects.for_team(self.team.id).get().secret == "old_secret_value"

    def test_rotate_requires_fresh_session(self):
        self._make_admin()
        session = self.client.session
        # login() stamps both keys and the freshness window takes their max, so age both.
        stale = time.time() - django_settings.SESSION_SENSITIVE_ACTIONS_AGE - 1
        session[django_settings.SESSION_COOKIE_CREATED_AT_KEY] = stale
        session[django_settings.SESSION_LAST_REAUTH_AT_KEY] = stale
        session.save()

        response = self.client.post(self._url("rotate/"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "sensitive_action_required_reauth"

    @parameterized.expand([("get",), ("post",)])
    def test_scoped_tokens_cannot_reach_the_raw_secret(self, method):
        self._make_admin()
        key_value = self.create_personal_api_key_with_scopes(["*"])
        self.client.logout()

        url = self._url() if method == "get" else self._url("rotate/")
        response = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f"Bearer {key_value}")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("get",), ("post",)])
    def test_impersonation_jwt_cannot_reach_the_raw_secret(self, method):
        # A JWT carries no session, so it would skip the freshness check if auth let it in.
        self._make_admin()
        token = encode_jwt({"id": self.user.id}, timedelta(minutes=15), PosthogJwtAudience.IMPERSONATED_USER)
        self.client.logout()

        url = self._url() if method == "get" else self._url("rotate/")
        response = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f"Bearer {token}")

        assert response.status_code == status.HTTP_403_FORBIDDEN
