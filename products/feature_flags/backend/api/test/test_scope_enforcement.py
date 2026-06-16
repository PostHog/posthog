from types import SimpleNamespace

from unittest import TestCase

from parameterized import parameterized

from posthog.auth import (
    IDJagAccessTokenAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
)

from products.feature_flags.backend.api.feature_flag import _scope_audit_identity


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
