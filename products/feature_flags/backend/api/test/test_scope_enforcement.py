from types import SimpleNamespace

from posthog.test.base import APIBaseTest
from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized
from rest_framework.exceptions import PermissionDenied

from posthog.auth import (
    IDJagAccessTokenAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
)
from posthog.models import Organization, Team

from products.feature_flags.backend.api.feature_flag import (
    _is_enforce_feature_flag_write_scope_enabled,
    _scope_audit_identity,
    assert_feature_flag_write_scope,
)


def _make(cls, **attrs):
    instance = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(instance, key, value)
    return instance


class TestScopeAuditIdentity(TestCase):
    @parameterized.expand(
        [
            (
                "personal_api_key",
                _make(
                    PersonalAPIKeyAuthentication,
                    personal_api_key=SimpleNamespace(scopes=["survey:write"], id="pak_1", label="key"),
                ),
                ["survey:write"],
                "personal_api_key",
            ),
            (
                "oauth_access_token",
                _make(OAuthAccessTokenAuthentication, access_token=SimpleNamespace(scope="survey:write a:b", id=7)),
                ["survey:write", "a:b"],
                "oauth_access_token",
            ),
            (
                "id_jag_access_token",
                _make(IDJagAccessTokenAuthentication, scopes=["early_access_feature:write"]),
                ["early_access_feature:write"],
                "id_jag_access_token",
            ),
            (
                "project_secret_api_key",
                _make(
                    ProjectSecretAPIKeyAuthentication,
                    project_secret_api_key=SimpleNamespace(scopes=["survey:write"], id=3),
                ),
                ["survey:write"],
                "project_secret_api_key",
            ),
        ]
    )
    def test_extracts_scopes_for_every_token_type(self, _name, authenticator, expected_scopes, expected_kind):
        identity = _scope_audit_identity(authenticator)
        assert identity is not None
        scopes, auth_kind, _auth_id, _auth_label = identity
        assert scopes == expected_scopes
        assert auth_kind == expected_kind

    def test_returns_none_for_session_auth(self):
        assert _scope_audit_identity(object()) is None
        assert _scope_audit_identity(None) is None


class TestEnforcementMessageByTokenType(TestCase):
    @parameterized.expand(
        [
            (
                "personal_api_key",
                _make(
                    PersonalAPIKeyAuthentication,
                    personal_api_key=SimpleNamespace(scopes=["survey:write"], id="pak_1", label="key"),
                ),
                True,
            ),
            (
                "oauth_access_token",
                _make(OAuthAccessTokenAuthentication, access_token=SimpleNamespace(scope="survey:write", id=7)),
                False,
            ),
            (
                "id_jag_access_token",
                _make(IDJagAccessTokenAuthentication, scopes=["survey:write"]),
                False,
            ),
            (
                "project_secret_api_key",
                _make(
                    ProjectSecretAPIKeyAuthentication,
                    project_secret_api_key=SimpleNamespace(scopes=["survey:write"], id=3),
                ),
                False,
            ),
        ]
    )
    def test_only_personal_api_keys_get_the_settings_page_guidance(self, _name, authenticator, expects_settings_link):
        request = SimpleNamespace(successful_authenticator=authenticator, user=SimpleNamespace(id=1))
        with patch(
            "products.feature_flags.backend.api.feature_flag._is_enforce_feature_flag_write_scope_enabled",
            return_value=True,
        ):
            with self.assertRaises(PermissionDenied) as caught:
                assert_feature_flag_write_scope(
                    request,
                    action="survey.update.targeting_flag_filters",
                    resource_scope="survey:write",
                    team_id=1,
                )

        message = str(caught.exception.detail)
        assert "`feature_flag:write`" in message
        if expects_settings_link:
            assert "/settings/user-api-keys" in message
            assert "personal API key" in message
        else:
            assert "/settings/user-api-keys" not in message
            assert "personal API key" not in message


class TestEnforcementGateTargetsTeamOrg(APIBaseTest):
    def test_gate_evaluates_against_target_team_org_not_actor_org(self):
        # A user whose current org differs from the org owning the target team must be
        # gated by the *target* team's org, so it can't be dodged by switching orgs.
        other_org = Organization.objects.create(name="other org")
        other_team = Team.objects.create(organization=other_org, name="other team")
        request = SimpleNamespace(user=self.user)

        with patch(
            "products.feature_flags.backend.api.feature_flag.feature_enabled_or_false",
            return_value=True,
        ) as mock_feature_enabled:
            result = _is_enforce_feature_flag_write_scope_enabled(request, team_id=other_team.id)

        assert result is True
        groups = mock_feature_enabled.call_args.kwargs["groups"]
        assert groups["organization"] == str(other_org.id)
        assert groups["organization"] != str(self.organization.id)

    def test_gate_fails_closed_without_team_id(self):
        request = SimpleNamespace(user=self.user)
        assert _is_enforce_feature_flag_write_scope_enabled(request, team_id=None) is False

    def test_gate_returns_false_for_anonymous_user(self):
        request = SimpleNamespace(user=SimpleNamespace(is_anonymous=True))
        assert _is_enforce_feature_flag_write_scope_enabled(request, team_id=self.team.id) is False

    def test_gate_fails_closed_and_logs_on_error(self):
        # A nonexistent team raises during org resolution; the gate logs and fails open.
        request = SimpleNamespace(user=self.user)
        with patch("products.feature_flags.backend.api.feature_flag.logger") as mock_logger:
            result = _is_enforce_feature_flag_write_scope_enabled(request, team_id=999_999_999)
        assert result is False
        assert mock_logger.warning.called

    def test_gate_returns_feature_enabled_result(self):
        request = SimpleNamespace(user=self.user)
        with patch(
            "products.feature_flags.backend.api.feature_flag.feature_enabled_or_false",
            return_value=False,
        ):
            assert _is_enforce_feature_flag_write_scope_enabled(request, team_id=self.team.id) is False
