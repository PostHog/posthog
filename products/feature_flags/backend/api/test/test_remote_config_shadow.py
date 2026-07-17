# Temporary — delete with remote_config_shadow.py at the Rust port phase-3 cutover.
import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from rest_framework.response import Response

from posthog.auth import (
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    TeamSecretTokenAuthentication,
)

from products.feature_flags.backend.api import remote_config_shadow as shadow

# Matches REDACTED_PAYLOAD_VALUE on the Django and Rust sides: a quoted string returned to a
# secret-key caller on an encrypted flag — the most parity-sensitive value the shadow compares.
REDACTED = '"********* (encrypted)"'


def _request(authenticator=TeamSecretTokenAuthentication, authorization="Bearer phs_x", query=None):
    req = MagicMock()
    req.successful_authenticator = MagicMock(spec=authenticator) if authenticator else None
    req.headers = {"Authorization": authorization} if authorization else {}
    req.query_params.dict.return_value = query or {}
    return req


def _rust_response(status_code=200, content=b"", json_value=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json.return_value = json_value
    return resp


@pytest.fixture(autouse=True)
def _enable_shadow(settings):
    # The shadow is off by default in production; turn it on so these tests exercise the comparison.
    settings.REMOTE_CONFIG_SHADOW_ENABLED = True


def test_disabled_is_inert(settings):
    settings.REMOTE_CONFIG_SHADOW_ENABLED = False
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        shadow.shadow_compare_remote_config(_request(), Response("v"), project_id=1, key="f")
        session.get.assert_not_called()
        counter.labels.assert_not_called()


@pytest.mark.parametrize("authenticator", [None, OAuthAccessTokenAuthentication])
def test_unsupported_auth_is_skipped(authenticator):
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        shadow.shadow_compare_remote_config(_request(authenticator=authenticator), Response("v"), project_id=1, key="f")
        session.get.assert_not_called()
        counter.labels.assert_called_once_with(result="skipped")


@pytest.mark.parametrize(
    "authenticator",
    [TeamSecretTokenAuthentication, PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication],
)
def test_supported_auth_is_compared(authenticator):
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        session.get.return_value = _rust_response(200, b'"v"', "v")
        shadow.shadow_compare_remote_config(_request(authenticator=authenticator), Response("v"), project_id=1, key="f")
        session.get.assert_called_once()
        counter.labels.assert_called_once_with(result="match")


@pytest.mark.parametrize(
    "authenticator",
    [TeamSecretTokenAuthentication, PersonalAPIKeyAuthentication, ProjectSecretAPIKeyAuthentication],
)
def test_non_header_credential_is_skipped(authenticator):
    # Django also authenticates via ?personal_api_key= / request body, but Rust reads only the
    # Authorization header — so a non-header credential 401s on Rust. Skip rather than log a false mismatch.
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        shadow.shadow_compare_remote_config(
            _request(authenticator=authenticator, authorization=None), Response("v"), project_id=1, key="f"
        )
        session.get.assert_not_called()
        counter.labels.assert_called_once_with(result="skipped")


@override_settings(FEATURE_FLAGS_DEFINITIONS_SERVICE_URL="http://rust:3001")
def test_builds_canonical_rust_url():
    with patch.object(shadow, "_SHADOW_SESSION") as session, patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS"):
        session.get.return_value = _rust_response(200, b'"v"', "v")
        shadow.shadow_compare_remote_config(_request(query={"token": "phc_x"}), Response("v"), project_id=7, key="flag")
        assert session.get.call_args.args[0] == "http://rust:3001/api/projects/7/feature_flags/flag/remote_config"
        assert session.get.call_args.kwargs["params"] == {"token": "phc_x"}
        assert session.get.call_args.kwargs["headers"] == {"Authorization": "Bearer phs_x"}


@pytest.mark.parametrize(
    "django_response, rust_response, expected",
    [
        (Response("v", status=200), _rust_response(200, b'"v"', "v"), "match"),
        (Response("v", status=200), _rust_response(200, b'"other"', "other"), "mismatch"),
        (Response(status=404), _rust_response(200, b'"v"', "v"), "mismatch"),
        (Response(None, status=200), _rust_response(200, b"", None), "match"),
        (Response(status=404), _rust_response(404, b"", None), "match"),
        (Response(REDACTED, status=200), _rust_response(200, REDACTED.encode(), REDACTED), "match"),
        (Response({"a": 1}, status=200), _rust_response(200, b'{"a": 1}', {"a": 1}), "match"),
        (Response({"a": 1}, status=200), _rust_response(200, b'{"a": 2}', {"a": 2}), "mismatch"),
    ],
)
def test_compare_outcomes(django_response, rust_response, expected):
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        session.get.return_value = rust_response
        shadow.shadow_compare_remote_config(_request(), django_response, project_id=1, key="f")
        counter.labels.assert_called_once_with(result=expected)


def test_mismatch_logs_only_metadata_not_bodies():
    # Decrypted remote config payloads are secrets — the mismatch log carries only flag/project/statuses.
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS"),
        patch.object(shadow, "logger") as log,
    ):
        session.get.return_value = _rust_response(404, b"", None)
        shadow.shadow_compare_remote_config(_request(), Response("secret-plaintext", status=200), project_id=1, key="f")
        log.warning.assert_called_once()
        assert set(log.warning.call_args.kwargs) == {"flag", "project_id", "django_status", "rust_status"}


def test_rust_error_is_swallowed():
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        session.get.side_effect = RuntimeError("boom")
        shadow.shadow_compare_remote_config(_request(), Response("v"), project_id=1, key="f")
        counter.labels.assert_called_once_with(result="error")


def test_non_json_rust_body_is_a_mismatch_not_a_false_match():
    rust = _rust_response(200, b"<html>502 Bad Gateway</html>")
    rust.json.side_effect = ValueError("not json")
    with (
        patch.object(shadow, "_SHADOW_SESSION") as session,
        patch.object(shadow, "REMOTE_CONFIG_SHADOW_COMPARISONS") as counter,
    ):
        session.get.return_value = rust
        shadow.shadow_compare_remote_config(_request(), Response(None, status=200), project_id=1, key="f")
        counter.labels.assert_called_once_with(result="mismatch")
