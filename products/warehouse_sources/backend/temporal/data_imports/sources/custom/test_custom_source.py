import io
import gzip
import json
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from requests import Response
from urllib3.response import HTTPResponse

from posthog.models import User

from products.warehouse_sources.backend.models import ExternalDataSource
from products.warehouse_sources.backend.models.custom_oauth2_integration import CustomOAuth2Integration
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAUTH2_PERMANENT_ERROR_MARKER,
    APIKeyAuth,
    BearerTokenAuth,
    HttpBasicAuth,
    OAuth2Auth,
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.custom.source import (
    MAX_MANIFEST_RESOURCES,
    PREVIEW_MAX_FANOUT_PARENTS,
    PREVIEW_MAX_ROWS,
    PROBE_CONNECT_TIMEOUT,
    PROBE_MAX_RESOURCES,
    PROBE_READ_TIMEOUT,
    CustomSource,
    FanoutChain,
    ManifestValidationError,
    PreviewResponseTooLargeError,
    _fanout_chain,
    _inject_oauth2_integration_secrets,
    _json_type_label,
    _PreviewSession,
    _read_capped_text,
    _redact_secrets,
    _validate_resource_graph,
    manifest_request_hosts,
    validate_manifest_structure,
    validate_manifest_urls,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CustomSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.types import IncrementalFieldType

AUTH_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth"
SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session"


def _token_response(status_code: int = 200, payload: dict[str, Any] | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    # The token exchange reads a capped `response.raw.read(...)` then json.loads — seed the raw body.
    response.raw.read.return_value = json.dumps(payload if payload is not None else {}).encode()
    return response


def validate_manifest(manifest: Any) -> None:
    # Full-validation composite (structure + graph). Production runs the two
    # levels separately — permissive structural checks on stored-manifest
    # reads, graph rules on the API validation paths — so the composite lives
    # here with the tests that use it.
    validate_manifest_structure(manifest)
    _validate_resource_graph(manifest)


def _minimal_manifest(base_url: str = "https://api.example.com") -> dict:
    """A structurally valid manifest. Auth carries no inline credential — the
    secret lives in the separate auth_* config fields."""
    return {
        "client": {
            "base_url": base_url,
            "auth": {"type": "bearer"},
        },
        "resources": [
            {
                "name": "users",
                "primary_key": "id",
                "endpoint": {"path": "/users", "data_selector": "data"},
            }
        ],
    }


class TestValidateManifest(SimpleTestCase):
    def test_accepts_minimal_manifest(self):
        validate_manifest(_minimal_manifest())

    @parameterized.expand(
        [
            ("not a dict", "must be a JSON object"),
            ({}, "Field required"),
            (
                {"client": {"base_url": "https://x"}, "resources": []},
                "at least 1",
            ),
            ({"client": {}, "resources": [{}]}, "base_url"),
            (
                {"client": {"base_url": "x"}, "resources": [{"name": "users"}]},
                "endpoint",
            ),
        ]
    )
    def test_rejects_malformed(self, manifest, expected_substring):
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert expected_substring in str(ctx.exception)

    def test_empty_required_strings_give_plain_message(self):
        # Empty required fields used to surface pydantic's raw "String should have at
        # least 1 character" with positional paths; assert the friendlier, JSON-mirroring form.
        manifest = {"client": {"base_url": ""}, "resources": [{"name": "", "endpoint": {"path": ""}}]}
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        message = str(ctx.exception)
        assert "client.base_url: must not be empty" in message
        assert "resources[0].name: must not be empty" in message
        assert "resources[0].endpoint.path: must not be empty" in message

    def test_rejects_duplicate_resource_names(self):
        manifest = _minimal_manifest()
        manifest["resources"].append({**manifest["resources"][0]})
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "Duplicate" in str(ctx.exception)

    def test_rejects_too_many_resources(self):
        # An unbounded resource count turns the create-time probe into an outbound
        # request amplifier — the manifest is capped at MAX_MANIFEST_RESOURCES.
        manifest = _minimal_manifest()
        manifest["resources"] = [
            {"name": f"r{i}", "endpoint": {"path": f"/r{i}"}} for i in range(MAX_MANIFEST_RESOURCES + 1)
        ]
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "at most" in str(ctx.exception)

    def test_accepts_resource_count_at_limit(self):
        manifest = _minimal_manifest()
        manifest["resources"] = [
            {"name": f"r{i}", "endpoint": {"path": f"/r{i}"}} for i in range(MAX_MANIFEST_RESOURCES)
        ]
        validate_manifest(manifest)

    def test_rejects_unknown_auth_type(self):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "oauth"}
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "auth.type" in str(ctx.exception)

    @parameterized.expand(["TRACE", "PUT", "PATCH", "DELETE"])
    def test_rejects_non_read_http_method(self, method):
        # A sync only fetches — GET and POST are the only accepted methods;
        # write verbs must be rejected so a manifest can't mutate upstream data.
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["method"] = method
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "method" in str(ctx.exception)

    @parameterized.expand(["GET", "POST", "get", "post"])
    def test_accepts_read_http_method(self, method):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["method"] = method
        validate_manifest(manifest)

    def test_accepts_endpoint_params_and_json_body(self):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"] = {
            "path": "/search",
            "method": "POST",
            "params": {"limit": 100},
            "json": {"query": "foo"},
        }
        validate_manifest(manifest)

    @parameterized.expand([("json", ["not", "an", "object"]), ("params", ["nope"])])
    def test_rejects_non_object_params_or_json(self, field, value):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"][field] = value
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert field in str(ctx.exception)

    @parameterized.expand(
        [
            ("token", {"type": "bearer", "token": "leaked"}),
            ("api_key", {"type": "api_key", "api_key": "leaked"}),
            ("password", {"type": "http_basic", "username": "alice", "password": "leaked"}),
            (
                "client_secret",
                {
                    "type": "oauth2",
                    "client_id": "cid",
                    "token_url": "https://auth.example.com/t",
                    "client_secret": "leaked",
                },
            ),
            (
                "refresh_token",
                {
                    "type": "oauth2",
                    "client_id": "cid",
                    "token_url": "https://auth.example.com/t",
                    "grant_type": "refresh_token",
                    "refresh_token": "leaked",
                },
            ),
            (
                "access_token",
                {
                    "type": "oauth2",
                    "client_id": "cid",
                    "token_url": "https://auth.example.com/t",
                    "access_token": "leaked",
                },
            ),
            # The OAuth2 token-request knobs are forwarded to the token endpoint but stored in the
            # non-secret manifest, so a secret hidden in them must be rejected too.
            (
                "extra_token_request_params.client_secret",
                {
                    "type": "oauth2",
                    "client_id": "cid",
                    "token_url": "https://auth.example.com/t",
                    "extra_token_request_params": {"client_secret": "leaked"},
                },
            ),
            (
                "token_request_headers.Authorization",
                {
                    "type": "oauth2",
                    "client_id": "cid",
                    "token_url": "https://auth.example.com/t",
                    "token_request_headers": {"Authorization": "Bearer leaked"},
                },
            ),
        ]
    )
    def test_rejects_inline_credentials(self, _name, auth):
        # Credentials belong in the dedicated secret auth_* fields, never inline
        # in the manifest — the manifest field is non-secret and round-trips to the client.
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "must not be embedded" in str(ctx.exception)

    def test_accepts_valid_oauth2_manifest(self):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
            "grant_type": "client_credentials",
        }
        validate_manifest(manifest)

    @parameterized.expand(
        [
            ("missing_client_id", {"type": "oauth2", "token_url": "https://auth.example.com/t"}),
            ("missing_token_url", {"type": "oauth2", "client_id": "cid"}),
        ]
    )
    def test_rejects_oauth2_missing_required_fields(self, _name, auth):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "OAuth2 auth requires" in str(ctx.exception)

    def test_rejects_oauth2_authorization_code_grant(self):
        # authorization_code needs an interactive consent flow — out of scope for headless syncs.
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/t",
            "grant_type": "authorization_code",
        }
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        assert "grant_type" in str(ctx.exception)


class TestValidateManifestUrls(SimpleTestCase):
    @parameterized.expand(
        [
            ("http_127", "http://127.0.0.1/api"),
            ("https_loopback", "https://127.0.0.1/api"),
            ("https_private", "https://10.0.0.1/api"),
            ("https_imds", "https://169.254.169.254/latest/meta-data/"),
            ("http_public", "http://api.example.com"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    def test_rejects_unsafe_or_http(self, _name: str, base_url: str):
        manifest = _minimal_manifest(base_url=base_url)
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok, err

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda host, team_id: (host != "127.0.0.1", None if host != "127.0.0.1" else "blocked"),
    )
    def test_rejects_absolute_resource_path_when_internal(self, _mock):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["path"] = "http://127.0.0.1/leak"
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "users" in (err or "")

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda host, team_id: (host != "127.0.0.1", None if host != "127.0.0.1" else "blocked"),
    )
    def test_rejects_whitespace_prefixed_internal_path(self, _mock):
        # A leading space makes the raw `startswith` check miss the absolute URL, but urljoin
        # strips it and the sync reaches 127.0.0.1 — the validator must resolve it the same way.
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["path"] = " https://127.0.0.1/leak"
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "users" in (err or "")

    @parameterized.expand(
        [
            ("http_public", "http://api.example.com"),
            ("http_private", "http://10.0.0.1/api"),
            ("https_loopback", "https://127.0.0.1/api"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="")
    def test_self_hosted_skips_host_check(self, _name: str, base_url: str):
        # _is_host_safe is a no-op outside of cloud, and http:// is permitted.
        # A self-hosted instance must be able to reach internal/private hosts.
        manifest = _minimal_manifest(base_url=base_url)
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert ok, err

    @parameterized.expand(
        [
            ("https_loopback", "https://127.0.0.1/oauth2/token"),
            ("https_imds", "https://169.254.169.254/token"),
            ("http_public", "http://auth.example.com/token"),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda host, team_id: (
            host not in {"127.0.0.1", "169.254.169.254"},
            None if host not in {"127.0.0.1", "169.254.169.254"} else "blocked",
        ),
    )
    def test_rejects_unsafe_or_http_oauth2_token_url(self, _name: str, token_url: str, _mock):
        # The token endpoint is vetted like base_url — internal/private hosts and plaintext
        # http on Cloud are rejected (defense-in-depth alongside the Smokescreen egress proxy).
        # base_url's host is allowed by the stub so the token_url check is the one under test.
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "oauth2", "client_id": "cid", "token_url": token_url}
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert not ok
        assert "token_url" in (err or "")

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda host, team_id: (True, None),
    )
    def test_accepts_safe_https_oauth2_token_url(self, _mock):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/oauth2/token",
        }
        ok, err = validate_manifest_urls(manifest, team_id=999)
        assert ok, err


class TestCustomSourceAssembleManifest(SimpleTestCase):
    def test_rejects_invalid_json(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        with self.assertRaises(ManifestValidationError):
            source._assemble_manifest(config)

    def test_returns_parsed_manifest(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        manifest = source._assemble_manifest(config)
        assert manifest["client"]["base_url"] == "https://api.example.com"

    @parameterized.expand(
        [
            ("bearer", {"type": "bearer"}, {"auth_token": "ya29.secret"}, "token", "ya29.secret"),
            (
                "api_key",
                {"type": "api_key", "name": "X-API-Key", "location": "header"},
                {"auth_api_key": "sk_test"},
                "api_key",
                "sk_test",
            ),
            (
                "http_basic",
                {"type": "http_basic", "username": "alice"},
                {"auth_password": "hunter2"},
                "password",
                "hunter2",
            ),
        ]
    )
    def test_injects_auth_secret_for_type(self, _name, auth, secret_kwargs, expected_key, expected_value):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), **secret_kwargs)
        assembled = source._assemble_manifest(config)
        assert assembled["client"]["auth"][expected_key] == expected_value

    def test_leaves_auth_alone_when_no_secret_provided(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        assembled = source._assemble_manifest(config)
        assert "token" not in assembled["client"]["auth"]

    def test_injects_oauth2_secrets_and_preserves_manifest_fields(self):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
            "grant_type": "refresh_token",
            "scopes": "read:users",
        }
        source = CustomSource()
        config = CustomSourceConfig(
            manifest_json=json.dumps(manifest),
            auth_oauth2_client_secret="cs_secret",
            auth_oauth2_refresh_token="rt_secret",
        )
        auth = source._assemble_manifest(config)["client"]["auth"]
        # Secrets injected from the config fields...
        assert auth["client_secret"] == "cs_secret"
        assert auth["refresh_token"] == "rt_secret"
        # ...and the non-secret manifest fields left intact.
        assert auth["client_id"] == "cid"
        assert auth["token_url"] == "https://auth.example.com/token"
        assert auth["grant_type"] == "refresh_token"
        assert auth["scopes"] == "read:users"

    def test_oauth2_leaves_secrets_absent_when_not_provided(self):
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
        }
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        auth = source._assemble_manifest(config)["client"]["auth"]
        assert "client_secret" not in auth
        assert "refresh_token" not in auth

    def test_oauth2_skips_static_secrets_when_integration_backed(self):
        # When the source points at a CustomOAuth2Integration, the static job_inputs secrets must NOT be
        # injected here — the row is the source of truth and supplies them at sync time. Leaking the
        # static ones would let a stale/duplicate secret override the model's live credentials.
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
        }
        source = CustomSource()
        config = CustomSourceConfig(
            manifest_json=json.dumps(manifest),
            auth_oauth2_client_secret="cs_secret",
            auth_oauth2_refresh_token="rt_secret",
            auth_oauth2_integration_id="11111111-1111-1111-1111-111111111111",
        )
        auth = source._assemble_manifest(config)["client"]["auth"]
        assert "client_secret" not in auth
        assert "refresh_token" not in auth


class TestCustomSourceOAuth2IntegrationWiring(BaseTest):
    def _make_integration(
        self, *, external_data_source: ExternalDataSource | None = None, created_by=None, **secret_overrides
    ) -> CustomOAuth2Integration:
        return CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            external_data_source=external_data_source,
            created_by=created_by,
            config={"token_url": "https://auth.example.com/token", "client_id": "cid", "grant_type": "refresh_token"},
            sensitive_config={"client_secret": "cs", "refresh_token": "orig-RT", **secret_overrides},
        )

    def _make_source(self, name: str = "a") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=f"sid-{name}",
            connection_id=f"cid-{name}",
            status="Completed",
            source_type="Custom",
        )

    def _oauth2_manifest(self) -> dict:
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
            "grant_type": "refresh_token",
        }
        return manifest

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_injects_static_bearer_and_writes_back_rotation(self, mock_session):
        # The Calendly path end-to-end at the wiring seam: minting up front persists the rotated
        # single-use refresh token, and the manifest is seeded with a static bearer (the minted access
        # token, manages_own_token=False) — never the refresh_token/client_secret — so the engine
        # structurally can't re-mint and burn an unpersisted rotation.
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600, "refresh_token": "rotated-RT"}
        )
        integration = self._make_integration()
        manifest = self._oauth2_manifest()

        _inject_oauth2_integration_secrets(manifest, str(integration.pk), self.team.pk)

        auth = manifest["client"]["auth"]
        assert auth["access_token"] == "minted-AT"
        assert auth["manages_own_token"] is False
        # No minting material reaches the engine.
        assert "refresh_token" not in auth
        assert "client_secret" not in auth
        # The rotation was persisted, so the next sync reads the rotated token from the row.
        fresh = CustomOAuth2Integration.objects.for_team(self.team.pk).get(pk=integration.pk)
        assert fresh.sensitive_config["refresh_token"] == "rotated-RT"

    @freeze_time("2025-01-01T00:00:00Z")
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_reuses_cached_token_without_minting(self, mock_session):
        # A still-valid cached token means no mint at all — the manifest is seeded straight from the row.
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        integration = self._make_integration(access_token="cached-AT", token_expiry=future)
        manifest = self._oauth2_manifest()

        _inject_oauth2_integration_secrets(manifest, str(integration.pk), self.team.pk)

        mock_session.return_value.post.assert_not_called()
        auth = manifest["client"]["auth"]
        assert auth["access_token"] == "cached-AT"
        assert auth["manages_own_token"] is False
        # No refresh material is seeded — the engine treats it as a static bearer and never mints.
        assert "refresh_token" not in auth

    @freeze_time("2025-01-01T00:00:00Z")
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_post_injection_manifest_builds_static_bearer_that_never_mints(self, mock_session):
        # End-to-end seam: feed the injected client.auth through the engine's own auth construction
        # (`create_auth` -> `auth_class(**exclude_keys(...))`) and drive a request. manages_own_token=False
        # must survive the unpacking and short-circuit minting — the token carries no expiry, so without
        # the flag the engine would treat it as expired and mint (burning an unpersisted rotation).
        # A key/kwarg rename would also crash construction here. No token-endpoint POST may happen.
        future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        integration = self._make_integration(access_token="cached-AT", token_expiry=future)
        manifest = self._oauth2_manifest()

        _inject_oauth2_integration_secrets(manifest, str(integration.pk), self.team.pk)

        auth = create_auth(manifest["client"]["auth"])
        assert isinstance(auth, OAuth2Auth)
        assert auth.manages_own_token is False
        request = MagicMock()
        request.headers = {}
        auth(request)
        assert request.headers["Authorization"] == "Bearer cached-AT"
        mock_session.return_value.post.assert_not_called()

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_validate_credentials_mints_through_integration(self, mock_token_session, mock_probe_session):
        # The bug: an integration-backed OAuth2 source has no refresh token in job_inputs, so
        # validate_credentials used to build a refresh_token-grant OAuth2Auth with no token and fail the
        # pre-mint with "A refresh_token is required". The fix seeds the manifest from the row first, so
        # validation mints through the integration and the data probe reuses the seeded token.
        mock_token_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600}
        )
        mock_probe_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        integration = self._make_integration()
        config = CustomSourceConfig(
            manifest_json=json.dumps(self._oauth2_manifest()),
            auth_oauth2_integration_id=str(integration.pk),
        )

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk)

        assert ok, err
        assert "refresh_token is required" not in (err or "")

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_validate_credentials_does_not_re_mint_for_integration_backed(self, mock_token_session, mock_probe_session):
        # The rotation-without-writeback guard: for an integration-backed source the token is minted once
        # through the row (which persists the rotated single-use refresh token). The data probe must reuse
        # that seeded token and NOT mint a second time — a second mint would rotate the refresh token
        # without writing it back, orphaning the row on a consumed token. Assert exactly one token POST,
        # and that the stored refresh token is the one the integration path rotated to (not double-rotated).
        mock_token_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600, "refresh_token": "rotated-RT"}
        )
        mock_probe_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        integration = self._make_integration()
        config = CustomSourceConfig(
            manifest_json=json.dumps(self._oauth2_manifest()),
            auth_oauth2_integration_id=str(integration.pk),
        )

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk)

        assert ok, err
        assert mock_token_session.return_value.post.call_count == 1
        fresh = CustomOAuth2Integration.objects.for_team(self.team.pk).get(pk=integration.pk)
        assert fresh.sensitive_config["refresh_token"] == "rotated-RT"

    def test_validate_credentials_missing_integration_returns_clear_error(self):
        # A dangling / foreign auth_oauth2_integration_id must surface a clear message, not crash.
        config = CustomSourceConfig(
            manifest_json=json.dumps(self._oauth2_manifest()),
            auth_oauth2_integration_id="11111111-1111-1111-1111-111111111111",
        )

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk)

        assert not ok
        assert "no longer available" in (err or "")

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_validate_credentials_on_update_rejects_another_sources_integration(self, mock_session):
        # Updating source A must not validate with source B's integration UUID — the probe would otherwise
        # mint and send B's token to the (attacker-supplied) manifest host. Rejected before any mint.
        owner = self._make_source("owner")
        attacker = self._make_source("attacker")
        integration = self._make_integration(external_data_source=owner)
        config = CustomSourceConfig(
            manifest_json=json.dumps(self._oauth2_manifest()),
            auth_oauth2_integration_id=str(integration.pk),
        )

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk, source_id=str(attacker.pk))

        assert not ok
        assert "no longer available" in (err or "")
        mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_validate_credentials_on_create_rejects_bound_integration(self, mock_session):
        # Create/setup validation has no source yet, so an already-bound integration (another source's) is
        # rejected before its token is minted.
        owner = self._make_source("owner")
        integration = self._make_integration(external_data_source=owner)
        config = CustomSourceConfig(
            manifest_json=json.dumps(self._oauth2_manifest()),
            auth_oauth2_integration_id=str(integration.pk),
        )

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk)

        assert not ok
        assert "no longer available" in (err or "")
        mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_sync_rejects_integration_bound_to_another_source(self, mock_session):
        # The cross-source theft guard: at sync time a source cannot use an integration that belongs to a
        # different source, even within the same team — no token is minted and the lookup fails closed.
        owner = self._make_source("owner")
        attacker = self._make_source("attacker")
        integration = self._make_integration(external_data_source=owner)

        with self.assertRaises(CustomOAuth2Integration.DoesNotExist):
            _inject_oauth2_integration_secrets(
                self._oauth2_manifest(), str(integration.pk), self.team.pk, source_id=str(attacker.pk)
            )
        mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_sync_binds_unbound_integration_to_source_on_first_use(self, mock_session):
        # Trust-on-first-use: the first sync claims an unbound integration for its source, so no second
        # source can adopt it afterwards (the reject test above then applies).
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600}
        )
        source = self._make_source()
        integration = self._make_integration()  # unbound
        manifest = self._oauth2_manifest()

        _inject_oauth2_integration_secrets(manifest, str(integration.pk), self.team.pk, source_id=str(source.pk))

        fresh = CustomOAuth2Integration.objects.for_team(self.team.pk).get(pk=integration.pk)
        assert str(fresh.external_data_source_id) == str(source.pk)
        assert manifest["client"]["auth"]["access_token"] == "minted-AT"

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_sync_allows_integration_bound_to_its_own_source(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600}
        )
        source = self._make_source()
        integration = self._make_integration(external_data_source=source)
        manifest = self._oauth2_manifest()

        _inject_oauth2_integration_secrets(manifest, str(integration.pk), self.team.pk, source_id=str(source.pk))

        assert manifest["client"]["auth"]["access_token"] == "minted-AT"

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_preview_forbids_integration_bound_to_a_source(self, mock_session):
        # Preview runs before a source exists, so an already-bound integration (another source's) must be
        # rejected — otherwise a preview could read that source's data with its tokens.
        owner = self._make_source("owner")
        integration = self._make_integration(external_data_source=owner)

        with self.assertRaises(CustomOAuth2Integration.DoesNotExist):
            _inject_oauth2_integration_secrets(
                self._oauth2_manifest(), str(integration.pk), self.team.pk, forbid_bound=True
            )
        mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_inject_rejects_unbound_integration_owned_by_another_user(self, mock_session):
        # An unbound integration is a floating credential: in a request context (owner_user_id set) only its
        # creator may consume it, so a teammate can't adopt someone else's not-yet-bound integration UUID.
        integration = self._make_integration(created_by=self.user)  # unbound, created by self.user
        other_user = User.objects.create_and_join(self.organization, "other@example.com", "pw12345678")

        with self.assertRaises(CustomOAuth2Integration.DoesNotExist):
            _inject_oauth2_integration_secrets(
                self._oauth2_manifest(),
                str(integration.pk),
                self.team.pk,
                forbid_bound=True,
                owner_user_id=other_user.pk,
            )
        mock_session.return_value.post.assert_not_called()

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_inject_allows_unbound_integration_owned_by_requester(self, mock_session):
        mock_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600}
        )
        integration = self._make_integration(created_by=self.user)
        manifest = self._oauth2_manifest()

        _inject_oauth2_integration_secrets(
            manifest, str(integration.pk), self.team.pk, forbid_bound=True, owner_user_id=self.user.pk
        )

        assert manifest["client"]["auth"]["access_token"] == "minted-AT"


class TestCustomSourceOAuth2SecretAdoption(BaseTest):
    def _oauth2_manifest(self, token_url: str = "https://auth.example.com/token") -> dict:
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": token_url,
            "grant_type": "refresh_token",
        }
        return manifest

    def _static_config(self, **overrides) -> CustomSourceConfig:
        params = {
            "manifest_json": json.dumps(self._oauth2_manifest()),
            "auth_oauth2_client_secret": "cs",
            "auth_oauth2_refresh_token": "orig-RT",
            **overrides,
        }
        return CustomSourceConfig(**params)

    def _make_source(self, name: str = "a") -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=f"sid-{name}",
            connection_id=f"cid-{name}",
            status="Completed",
            source_type="Custom",
        )

    def _mock_mint(self, mock_token_session, mock_probe_session, rotated: str = "rotated-RT") -> None:
        mock_token_session.return_value.post.return_value = _token_response(
            payload={"access_token": "minted-AT", "expires_in": 3600, "refresh_token": rotated}
        )
        mock_probe_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_create_validation_adopts_static_secrets_into_row(self, mock_token_session, mock_probe_session):
        # The current-UI flow: static secrets typed on the source config screen are adopted into a
        # server-managed row during create validation, the config is rewritten to point at it (so the
        # persisted job_inputs never carry the raw secrets), and the mint happens through the row so
        # the rotated single-use refresh token is durably persisted.
        self._mock_mint(mock_token_session, mock_probe_session)
        config = self._static_config()

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk, owner_user_id=self.user.pk)

        assert ok, err
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).get()
        assert config.auth_oauth2_integration_id == str(row.pk)
        assert config.auth_oauth2_client_secret is None
        assert config.auth_oauth2_refresh_token is None
        assert row.external_data_source_id is None
        assert row.created_by_id == self.user.pk
        assert row.config["client_id"] == "cid"
        assert row.config["token_url"] == "https://auth.example.com/token"
        assert row.sensitive_config["client_secret"] == "cs"
        assert row.sensitive_config["refresh_token"] == "rotated-RT"

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_retry_reuses_unbound_row_and_mints_from_rotated_token(self, mock_token_session, mock_probe_session):
        # Preview-then-create (and failed-create retry) continuity for rotating providers: the second
        # validation re-submits the same original refresh token, which the provider already consumed.
        # It must match the caller's unbound row by client config and mint from the row's rotated
        # descendant — a fresh row (or a fingerprint miss overwriting the rotation) would mint from the
        # consumed original and fail with invalid_grant. The second call runs past the first token's
        # expiry, or the row would just reuse the still-valid cached access token without minting.
        self._mock_mint(mock_token_session, mock_probe_session, rotated="rotated-RT-1")
        first_config = self._static_config()
        with freeze_time("2025-01-01T00:00:00Z"):
            ok, err = CustomSource().validate_credentials(
                first_config, team_id=self.team.pk, owner_user_id=self.user.pk
            )
        assert ok, err

        self._mock_mint(mock_token_session, mock_probe_session, rotated="rotated-RT-2")
        second_config = self._static_config()
        with freeze_time("2025-01-01T02:00:00Z"):
            ok, err = CustomSource().validate_credentials(
                second_config, team_id=self.team.pk, owner_user_id=self.user.pk
            )

        assert ok, err
        assert second_config.auth_oauth2_integration_id == first_config.auth_oauth2_integration_id
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).get()
        assert mock_token_session.return_value.post.call_args.kwargs["data"]["refresh_token"] == "rotated-RT-1"
        assert row.sensitive_config["refresh_token"] == "rotated-RT-2"

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_newly_supplied_refresh_token_replaces_stored_one(self, mock_token_session, mock_probe_session):
        # A deliberately different refresh token (the recovery for a revoked grant) must replace the
        # stored rotation lineage — the fingerprint keep-rule only applies to a re-typed original.
        self._mock_mint(mock_token_session, mock_probe_session, rotated="rotated-RT-1")
        ok, err = CustomSource().validate_credentials(
            self._static_config(), team_id=self.team.pk, owner_user_id=self.user.pk
        )
        assert ok, err

        self._mock_mint(mock_token_session, mock_probe_session, rotated="rotated-RT-2")
        config = self._static_config(auth_oauth2_refresh_token="brand-new-RT")
        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk, owner_user_id=self.user.pk)

        assert ok, err
        assert mock_token_session.return_value.post.call_args.kwargs["data"]["refresh_token"] == "brand-new-RT"
        assert CustomOAuth2Integration.objects.for_team(self.team.pk).count() == 1

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_adoption_never_reuses_another_users_unbound_row(self, mock_token_session, mock_probe_session):
        # An unbound row is a floating credential scoped to its creator: a teammate submitting the same
        # client config must get their own row, not adopt (and mint through) someone else's.
        self._mock_mint(mock_token_session, mock_probe_session)
        other_user = User.objects.create_and_join(self.organization, "other-adopter@posthog.com", None)
        foreign = CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            created_by=other_user,
            config={"client_id": "cid", "token_url": "https://auth.example.com/token", "grant_type": "refresh_token"},
            sensitive_config={"client_secret": "foreign-cs", "refresh_token": "foreign-RT"},
        )
        config = self._static_config()

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk, owner_user_id=self.user.pk)

        assert ok, err
        assert config.auth_oauth2_integration_id != str(foreign.pk)
        foreign.refresh_from_db()
        assert foreign.sensitive_config["refresh_token"] == "foreign-RT"
        assert CustomOAuth2Integration.objects.for_team(self.team.pk).count() == 2

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_token_url_change_never_mints_the_rotated_token(self, mock_token_session, mock_probe_session):
        # An editor re-typing the consumed original token while repointing token_url must not get the
        # live rotated descendant — a credential they never possessed — minted against the new host.
        # The fingerprint keep-rule is suspended on a config change, so the mint carries only the
        # token the editor typed.
        self._mock_mint(mock_token_session, mock_probe_session)
        source = self._make_source("repointed")
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            created_by=self.user,
            external_data_source=source,
            config={"client_id": "cid", "token_url": "https://auth.example.com/token", "grant_type": "refresh_token"},
            sensitive_config={
                "client_secret": "cs",
                "refresh_token": "live-rotated-RT",
                "refresh_token_fingerprint": hashlib.sha256(b"orig-RT").hexdigest(),
            },
        )
        config = self._static_config(
            manifest_json=json.dumps(self._oauth2_manifest(token_url="https://editor-controlled.example.net/token")),
            auth_oauth2_integration_id=str(row.pk),
        )

        ok, err = CustomSource().validate_credentials(
            config, team_id=self.team.pk, source_id=str(source.pk), owner_user_id=self.user.pk
        )

        assert ok, err
        minted_with = mock_token_session.return_value.post.call_args
        assert minted_with.args[0] == "https://editor-controlled.example.net/token"
        assert minted_with.kwargs["data"]["refresh_token"] == "orig-RT"
        assert "live-rotated-RT" not in str(minted_with)

    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_foreign_pointer_is_rejected_before_any_row_mutation(self, mock_session):
        # Adoption refreshes a linked row's config from the submitted manifest — so authorization must
        # come first, or a create-seam caller pointing at another source's row could rewrite its
        # token_url (redirecting the next mint, with the stored client_secret, to an attacker host).
        victim_source = self._make_source("victim")
        victim_row = CustomOAuth2Integration.objects.for_team(self.team.pk).create(
            team=self.team,
            external_data_source=victim_source,
            config={"client_id": "cid", "token_url": "https://auth.example.com/token", "grant_type": "refresh_token"},
            sensitive_config={"client_secret": "cs", "refresh_token": "rt"},
        )
        config = self._static_config(
            manifest_json=json.dumps(self._oauth2_manifest(token_url="https://attacker.example.net/token")),
            auth_oauth2_integration_id=str(victim_row.pk),
        )

        ok, err = CustomSource().validate_credentials(config, team_id=self.team.pk, owner_user_id=self.user.pk)

        assert not ok
        victim_row.refresh_from_db()
        assert victim_row.config["token_url"] == "https://auth.example.com/token"
        assert victim_row.sensitive_config["client_secret"] == "cs"
        mock_session.return_value.post.assert_not_called()

    @patch(SOURCE_MODULE)
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_update_with_dangling_pointer_recovers_via_reentered_secrets(self, mock_token_session, mock_probe_session):
        # A source whose row was deleted must not be stuck on the dead pointer forever: re-entering the
        # secrets on the config screen adopts them into a fresh row bound to the source.
        self._mock_mint(mock_token_session, mock_probe_session)
        source = self._make_source("orphaned")
        config = self._static_config(auth_oauth2_integration_id="11111111-1111-1111-1111-111111111111")

        ok, err = CustomSource().validate_credentials(
            config, team_id=self.team.pk, source_id=str(source.pk), owner_user_id=self.user.pk
        )

        assert ok, err
        row = CustomOAuth2Integration.objects.for_team(self.team.pk).get()
        assert config.auth_oauth2_integration_id == str(row.pk)
        assert str(row.external_data_source_id) == str(source.pk)
        assert row.sensitive_config["client_secret"] == "cs"


class TestCustomSourceGetSchemas(SimpleTestCase):
    def test_returns_one_schema_per_resource(self):
        manifest = _minimal_manifest()
        manifest["resources"].append(
            {
                "name": "orders",
                "primary_key": ["order_id", "line_no"],
                "endpoint": {
                    "path": "/orders",
                    "data_selector": "data",
                    "incremental": {"cursor_path": "updated_at", "start_param": "since"},
                },
            }
        )
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schemas = source.get_schemas(config, team_id=999)
        assert {s.name for s in schemas} == {"users", "orders"}

        orders = next(s for s in schemas if s.name == "orders")
        assert orders.supports_incremental
        assert orders.incremental_fields[0]["field"] == "updated_at"
        assert orders.detected_primary_keys == ["order_id", "line_no"]

    def test_filters_by_names(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        schemas = source.get_schemas(config, team_id=999, names=["nonexistent"])
        assert schemas == []

    @parameterized.expand(
        [
            ("default_datetime", None, IncrementalFieldType.DateTime),
            ("declared_integer", "integer", IncrementalFieldType.Integer),
            ("unknown_falls_back", "bogus", IncrementalFieldType.DateTime),
        ]
    )
    def test_incremental_cursor_type_from_manifest(self, _name, declared, expected):
        manifest = _minimal_manifest()
        incremental: dict = {"cursor_path": "cursor"}
        if declared is not None:
            incremental["cursor_type"] = declared
        manifest["resources"][0]["endpoint"]["incremental"] = incremental

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schema = source.get_schemas(config, team_id=999)[0]
        assert schema.incremental_fields[0]["type"] == expected
        assert schema.incremental_fields[0]["field_type"] == expected


def _oauth2_manifest() -> dict:
    manifest = _minimal_manifest()
    manifest["client"]["auth"] = {
        "type": "oauth2",
        "client_id": "cid",
        "token_url": "https://auth.example.com/oauth2/token",
    }
    return manifest


class TestCustomSourceValidateCredentials(SimpleTestCase):
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_true_on_2xx(self, mock_session):
        response = MagicMock(status_code=200, text="{}")
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert err is None

    @patch.object(
        OAuth2Auth,
        "_obtain_token",
        side_effect=OAuth2AuthRequestError(
            "HTTP 401 from the OAuth2 token endpoint: invalid_client: bad creds",
            error_code="invalid_client",
            is_permanent=True,
        ),
    )
    def test_oauth2_probe_permanent_token_error_blocks_with_clear_message(self, _mock_mint):
        # A bad client_secret / token_url must fail at create time with a pointed token-endpoint
        # message — not the generic "resource unreachable" of the data probe.
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_oauth2_manifest()), auth_oauth2_client_secret="cs")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "OAuth2 token endpoint rejected" in (err or "")
        assert "invalid_client" in (err or "")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    @patch.object(
        OAuth2Auth,
        "_obtain_token",
        side_effect=OAuth2AuthRequestError("HTTP 503 from the OAuth2 token endpoint", is_permanent=False),
    )
    def test_oauth2_probe_transient_token_error_does_not_block(self, _mock_mint, mock_session):
        # A 429 / 5xx at the token endpoint during the create-time probe is transient — it must
        # not block creation; the first real sync retries it. The data probe is skipped entirely
        # (no minted token to authenticate with), so the probe session is never even built — assert
        # that, not a mocked 200 that would hide the real fall-through behavior.
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_oauth2_manifest()), auth_oauth2_client_secret="cs")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        mock_session.assert_not_called()

    @freeze_time("2025-01-01T00:00:00Z")
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_oauth2_minted_token_joins_probe_redaction(self, mock_session):
        # The pre-mint runs before the probe session is built, so the freshly-minted access token
        # (and the static client_secret) are both registered for redaction on the data probe.
        mock_session.return_value.request.return_value = MagicMock(status_code=200)

        def fake_mint(self_auth, timeout=None):
            self_auth.token = "minted-xyz"
            self_auth.token_expiry = datetime.now(UTC) + timedelta(hours=1)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_oauth2_manifest()), auth_oauth2_client_secret="cs_secret")
        with patch.object(OAuth2Auth, "_obtain_token", autospec=True, side_effect=fake_mint):
            ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        redact = mock_session.call_args.kwargs["redact_values"]
        assert "cs_secret" in redact
        assert "minted-xyz" in redact

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_body_snippet_redacts_echoed_credential(self, mock_session):
        # An upstream that echoes the sent credential in its 401/403 body must not leak it into the
        # user-facing error — the snippet is run through _redact_secrets before being surfaced.
        response = MagicMock(status_code=401)
        response.headers = {}
        response.raw.read.return_value = b"unauthorized: token sk_secret_value is invalid"
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="sk_secret_value")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "sk_secret_value" not in (err or "")
        assert "***" in (err or "")

    @parameterized.expand([401, 403])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_false_on_auth_rejection(self, status_code, mock_session):
        response = MagicMock(status_code=status_code, text="unauthorized")
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert str(status_code) in (err or "")

    @parameterized.expand([404, 405, 429, 500])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_non_auth_error_status_does_not_block_creation(self, status_code, mock_session):
        # A 404/405/429/5xx is not a credential problem — it must not block
        # source creation; the real sync surfaces it if it persists.
        mock_session.return_value.request.return_value = MagicMock(status_code=status_code, text="nope")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probes_resources_until_auth_failure(self, mock_session):
        # A later (within-cap) resource fails auth — validation must catch it, not stop at the first.
        manifest = _minimal_manifest()
        manifest["resources"].append({"name": "orders", "endpoint": {"path": "/orders"}})
        mock_session.return_value.request.side_effect = [
            MagicMock(status_code=200),
            MagicMock(status_code=403),
        ]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert "orders" in (err or "")
        assert "403" in (err or "")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_caps_resource_count(self, mock_session):
        # The probe must hit at most PROBE_MAX_RESOURCES upstreams regardless of how many
        # resources the manifest declares — so the endpoint can't fan out one request per resource.
        manifest = _minimal_manifest()
        manifest["resources"] = [
            {"name": f"r{i}", "endpoint": {"path": f"/r{i}"}} for i in range(PROBE_MAX_RESOURCES + 3)
        ]
        mock_session.return_value.request.return_value = MagicMock(status_code=200)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_count == PROBE_MAX_RESOURCES

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_streams_and_caps_error_body(self, mock_session):
        # The probe opens responses with stream=True and reads only a bounded slice
        # of a 401/403 body for the error snippet — never buffering the full body.
        response = MagicMock(status_code=403)
        response.headers = {}
        response.raw.read.return_value = b"forbidden: token expired"
        mock_session.return_value.request.return_value = response

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        # The snippet came from the bounded raw read; had the code used response.text[:200]
        # the message would contain a MagicMock repr instead of the decoded bytes.
        assert "forbidden: token expired" in (err or "")
        assert mock_session.return_value.request.call_args.kwargs["stream"] is True
        response.close.assert_called_once()

    def test_read_capped_text_omits_compressed_body(self):
        # A gzip-encoded body would decode to binary garbage, so it must be omitted from
        # the snippet rather than echoed into a user-facing error — and never materialized.
        payload = b"\x00" * (20 * 1024 * 1024)
        compressed = gzip.compress(payload)
        assert len(payload) / len(compressed) > 100  # it really is a decompression bomb

        response = MagicMock()
        response.headers = {"Content-Encoding": "gzip"}
        response.raw = HTTPResponse(
            body=io.BytesIO(compressed),
            headers={"content-encoding": "gzip", "content-length": str(len(compressed))},
            status=403,
            preload_content=False,
        )
        assert _read_capped_text(response) == ""

    @parameterized.expand(
        [
            # A body that isn't valid UTF-8 (binary, or still-encoded) is dropped rather than
            # surfaced as replacement-character garbage.
            ("non_utf8", b"\x1f\x8b\x08\x00garbage\xff\xfe", ""),
            # A plain-text body is returned, stripped of surrounding whitespace.
            ("plain_text", b"  forbidden: token expired  ", "forbidden: token expired"),
        ]
    )
    def test_read_capped_text_non_compressed(self, _name, raw_bytes, expected):
        response = MagicMock()
        response.headers = {}
        response.raw.read.return_value = raw_bytes
        assert _read_capped_text(response) == expected

    def test_read_capped_text_returns_identity_encoded_body(self):
        # `Content-Encoding: identity` means no transformation, so the plain-text body
        # is still readable and must be surfaced rather than dropped.
        response = MagicMock()
        response.headers = {"Content-Encoding": "identity"}
        response.raw.read.return_value = b"forbidden: token expired"
        assert _read_capped_text(response) == "forbidden: token expired"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_attaches_query_location_api_key(self, mock_session):
        # An api_key with location 'query' must reach the probe request — the
        # probe builds auth via create_auth, the same path the real sync uses.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "api_key", "name": "apikey", "location": "query"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_api_key="sk_test")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        probe_auth = mock_session.return_value.request.call_args.kwargs["auth"]
        assert isinstance(probe_auth, APIKeyAuth)
        assert probe_auth.location == "query"
        assert probe_auth.api_key == "sk_test"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_replays_json_body(self, mock_session):
        # A POST endpoint with a JSON body must send that body in the probe, so
        # an endpoint that needs it doesn't answer differently at probe vs sync.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"] = {"path": "/search", "method": "POST", "json": {"query": "foo"}}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_args.kwargs["json"] == {"query": "foo"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_replays_static_query_params(self, mock_session):
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["params"] = {"limit": 100, "order": "asc"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_args.kwargs["params"] == {"limit": 100, "order": "asc"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_skips_incremental_param_specs(self, mock_session):
        # Dict-valued params are the engine's incremental/resolver specs, resolved
        # against cursor state at sync time — the probe has none, so it forwards
        # only the plain scalar params and drops the spec.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["params"] = {
            "limit": 100,
            "since": {"type": "incremental", "cursor_path": "updated_at", "initial_value": "2020-01-01"},
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err
        assert mock_session.return_value.request.call_args.kwargs["params"] == {"limit": 100}

    @parameterized.expand(
        [
            (
                "bearer",
                {"type": "bearer"},
                {"auth_token": "ya29.secret"},
                BearerTokenAuth,
                {"token": "ya29.secret"},
            ),
            (
                "api_key_header",
                {"type": "api_key", "name": "X-API-Key", "location": "header"},
                {"auth_api_key": "sk_h"},
                APIKeyAuth,
                {"api_key": "sk_h", "location": "header", "name": "X-API-Key"},
            ),
            (
                "api_key_cookie",
                {"type": "api_key", "name": "session", "location": "cookie"},
                {"auth_api_key": "sk_c"},
                APIKeyAuth,
                {"api_key": "sk_c", "location": "cookie", "name": "session"},
            ),
            (
                "api_key_param",
                {"type": "api_key", "name": "key", "location": "param"},
                {"auth_api_key": "sk_p"},
                APIKeyAuth,
                {"api_key": "sk_p", "location": "param", "name": "key"},
            ),
            (
                "http_basic",
                {"type": "http_basic", "username": "alice"},
                {"auth_password": "hunter2"},
                HttpBasicAuth,
                {"username": "alice", "password": "hunter2"},
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_attaches_auth_for_each_type(
        self, _name, auth_manifest, secret_kwargs, expected_cls, expected_attrs, mock_session
    ):
        # Every supported (auth type, location) combination must reach the probe
        # request via create_auth — the same code path the real sync uses.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = auth_manifest

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), **secret_kwargs)
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        probe_auth = mock_session.return_value.request.call_args.kwargs["auth"]
        assert isinstance(probe_auth, expected_cls)
        for attr, expected in expected_attrs.items():
            assert getattr(probe_auth, attr) == expected, f"{attr} mismatch"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_registers_credential_for_redaction(self, mock_session):
        # The secret must be handed to the tracked session as a redact value so
        # it's masked from logs/samples even when injected into a query param
        # whose name the denylist scrubber can't anticipate.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {"type": "api_key", "name": "subscription-key", "location": "query"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_api_key="sk_live_leaky")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        assert mock_session.call_args.kwargs["redact_values"] == ("sk_live_leaky",)

    @parameterized.expand(
        [
            # A connection-level failure surfaces a clean "could not reach" message.
            ("connection", requests.exceptions.ConnectionError("boom at 10.0.0.1"), "could not reach", "boom"),
            # A read timeout surfaces the configured timeouts, not the raw urllib3 dump.
            (
                "timeout",
                requests.Timeout("HTTPSConnectionPool(host='x'): Read timed out. (read timeout=10)"),
                "timed out",
                "HTTPSConnectionPool",
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_returns_false_on_network_error(self, _name, side_effect, expected_fragment, leaked_text, mock_session):
        # A connection-level failure (DNS, TLS, timeout) must surface as a credential validation
        # error pointing at the offending resource, without leaking the raw requests exception.
        mock_session.return_value.request.side_effect = side_effect

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert expected_fragment in (err or "")
        assert "users" in (err or "")
        assert leaked_text not in (err or "")

    def test_returns_false_on_invalid_manifest(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        ok, err = source.validate_credentials(config, team_id=999)
        assert not ok
        assert err is not None


class TestManifestRequestHosts(SimpleTestCase):
    def _manifest(self, base_url: str, resource_paths: list[str]) -> str:
        return json.dumps(
            {
                "client": {"base_url": base_url},
                "resources": [{"name": f"r{i}", "endpoint": {"path": p}} for i, p in enumerate(resource_paths)],
            }
        )

    def test_base_url_host(self):
        assert manifest_request_hosts(self._manifest("https://api.example.com/v1", ["/users"])) == frozenset(
            {"api.example.com"}
        )

    def test_absolute_resource_paths_add_hosts(self):
        # Relative paths inherit base_url's host; only absolute URLs introduce a new host.
        manifest = self._manifest("https://api.example.com", ["/users", "https://cdn.other.net/data"])
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "cdn.other.net"})

    def test_path_param_absolute_url_is_collected(self):
        # A scalar param bound into a "{placeholder}" becomes the request URL at sync time
        # (_bind_path_params), so its host must be tracked even though the literal path is relative.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {
                        "name": "r",
                        "endpoint": {"path": "{target}", "params": {"target": "https://attacker.example.net/"}},
                    }
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_path_param_split_scheme_is_resolved(self):
        # The absolute URL is split across the template and a param ("{scheme}://host" +
        # {"scheme": "https"}); neither piece is a URL on its own, but the bound path is.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {
                        "name": "r",
                        "endpoint": {"path": "{scheme}://attacker.example.net/data", "params": {"scheme": "https"}},
                    }
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_uppercase_scheme_absolute_path_adds_host(self):
        # urljoin treats `HTTPS://host` as absolute (schemes are case-insensitive), so a
        # mixed-case scheme must still register the new host — otherwise an editor who can't
        # read the stored secret could retarget the preserved credential past the re-entry gate.
        manifest = self._manifest("https://api.example.com", ["HTTPS://attacker.example.net/data"])
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_uppercase_scheme_split_across_param_adds_host(self):
        # Same retarget bypass via a split scheme: "{scheme}://host" + {"scheme": "HTTPS"}.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {
                        "name": "r",
                        "endpoint": {"path": "{scheme}://attacker.example.net/data", "params": {"scheme": "HTTPS"}},
                    }
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    @parameterized.expand(
        [
            ("leading_space", " https://attacker.example.net/data"),
            ("leading_tab", "\thttps://attacker.example.net/data"),
            ("leading_newline", "\nhttps://attacker.example.net/data"),
            ("leading_nul", "\x00https://attacker.example.net/data"),
            ("leading_space_uppercase", " HTTPS://attacker.example.net/data"),
        ]
    )
    def test_whitespace_prefixed_absolute_path_adds_host(self, _name, path):
        # urljoin strips leading whitespace/control chars before parsing the scheme, so the
        # sync requests attacker.example.net while a raw `startswith` check sees no new host —
        # the retarget guard must resolve the path the same way the engine does.
        manifest = self._manifest("https://api.example.com", [path])
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "attacker.example.net"})

    def test_url_param_not_referenced_in_path_is_ignored(self):
        # A URL-valued query param that isn't a path placeholder is a normal query value, not a
        # request destination — it must not be counted (avoids false re-entry prompts).
        manifest = json.dumps(
            {
                "client": {"base_url": "https://api.example.com"},
                "resources": [
                    {"name": "r", "endpoint": {"path": "/users", "params": {"callback": "https://other.net/"}}}
                ],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com"})

    def test_backslash_authority_resolves_to_real_host(self):
        # `https://evil\@trusted/` connects to `evil` (urllib3/WHATWG) even though urlparse
        # alone reads `trusted` — the guard must see the real destination, not be fooled.
        manifest = json.dumps(
            {
                "client": {"base_url": "https://attacker.example.net\\@api.example.com/"},
                "resources": [{"name": "r", "endpoint": {"path": "/users"}}],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"attacker.example.net"})

    def test_host_is_lowercased(self):
        assert manifest_request_hosts(self._manifest("https://API.Example.COM", [])) == frozenset({"api.example.com"})

    @parameterized.expand([("not json", "{nope}"), ("non_string", 123), ("none", None), ("json_array", "[1, 2]")])
    def test_unparseable_returns_empty(self, _name, raw):
        assert manifest_request_hosts(raw) == frozenset()

    def test_oauth2_token_url_host_is_tracked(self):
        # The token endpoint receives the stored client_secret, so its host must be in the
        # re-entry set — otherwise an editor who can't read the secret could repoint token_url
        # at a host they control while keeping the secret, exfiltrating it past the gate.
        manifest = json.dumps(
            {
                "client": {
                    "base_url": "https://api.example.com",
                    "auth": {"type": "oauth2", "client_id": "cid", "token_url": "https://auth.other.net/oauth2/token"},
                },
                "resources": [{"name": "r", "endpoint": {"path": "/users"}}],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com", "auth.other.net"})

    def test_non_oauth2_auth_token_url_is_ignored(self):
        # A stray token_url on a non-oauth2 auth is inert (no credential goes there), so it
        # must not register a host and trigger spurious re-entry prompts.
        manifest = json.dumps(
            {
                "client": {
                    "base_url": "https://api.example.com",
                    "auth": {"type": "bearer", "token_url": "https://auth.other.net/token"},
                },
                "resources": [{"name": "r", "endpoint": {"path": "/users"}}],
            }
        )
        assert manifest_request_hosts(manifest) == frozenset({"api.example.com"})


class TestCustomSourceSourceForPipeline(SimpleTestCase):
    def test_invalid_manifest_raises_non_retryable(self):
        # A permanent config error must fail fast, not burn the Temporal retry budget.
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, MagicMock(team_id=999))

    def test_missing_resource_raises_non_retryable(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        inputs = MagicMock(team_id=999, schema_name="nonexistent")
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.get_custom_oauth2_integration"
    )
    def test_missing_oauth2_integration_raises_non_retryable(self, mock_get_integration):
        # A dangling auth_oauth2_integration_id (deleted row / wrong team) raises DoesNotExist at the
        # sync seam. It's neither a ValueError nor a message the substring classifier matches, so without
        # explicit handling it would retry until the activity budget is exhausted — assert it fails fast.
        mock_get_integration.side_effect = CustomOAuth2Integration.DoesNotExist
        manifest = _minimal_manifest()
        manifest["client"]["auth"] = {
            "type": "oauth2",
            "client_id": "cid",
            "token_url": "https://auth.example.com/token",
        }
        source = CustomSource()
        config = CustomSourceConfig(
            manifest_json=json.dumps(manifest),
            auth_oauth2_integration_id="11111111-1111-1111-1111-111111111111",
        )
        inputs = MagicMock(team_id=999, schema_name="users")
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @parameterized.expand(
        [("default_asc", None, "asc"), ("explicit_asc", "asc", "asc"), ("explicit_desc", "desc", "desc")]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_sort_mode_threaded_to_source_response(self, _name, declared, expected, mock_resources):
        mock_resources.return_value = [_fake_resource("users")]
        manifest = _minimal_manifest()
        if declared is not None:
            manifest["resources"][0]["sort_mode"] = declared

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)
        assert response.sort_mode == expected

    @parameterized.expand(
        [
            ("opted_in", True, "2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
            ("opted_out_drops_value", False, "2024-01-01T00:00:00Z", None),
            ("opted_in_none", True, None, None),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_incremental_last_value_threaded_to_rest_engine(
        self, _name, should_use_incremental, last_value, expected, mock_resources
    ):
        # The high-watermark must only reach the REST engine when the schema is
        # configured for incremental sync — otherwise a full refresh would skip rows.
        mock_resources.return_value = [_fake_resource("users")]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()))
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=should_use_incremental,
            db_incremental_field_last_value=last_value,
        )
        source.source_for_pipeline(config, inputs)

        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] == expected

    @parameterized.expand(
        [
            ("auto", {"type": "auto"}),
            ("single_page", {"type": "single_page"}),
            ("json_response", {"type": "json_response", "next_url_path": "next"}),
            ("header_link", {"type": "header_link"}),
            ("cursor", {"type": "cursor", "cursor_path": "next_cursor", "cursor_param": "cursor"}),
            ("offset", {"type": "offset", "limit": 100}),
            ("page_number", {"type": "page_number", "page_param": "page"}),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_paginator_config_threaded_to_rest_engine(self, _name, paginator_config, mock_resources):
        # Every PaginatorType the REST engine knows about must round-trip through
        # the custom source — paginator config is passed through untouched and the
        # REST engine selects the paginator at sync time.
        mock_resources.return_value = [_fake_resource("users")]
        manifest = _minimal_manifest()
        manifest["client"]["paginator"] = paginator_config

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        source.source_for_pipeline(config, inputs)

        threaded_config = mock_resources.call_args.args[0]
        assert threaded_config["client"]["paginator"] == paginator_config

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_cursor_type_stripped_before_rest_engine(self, mock_resources):
        # cursor_type informs schema field typing but is not a valid kwarg for the
        # engine's Incremental(**config) — it must be removed before the manifest
        # reaches the REST engine, while the other incremental keys survive.
        mock_resources.return_value = [_fake_resource("users")]
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["incremental"] = {
            "cursor_path": "updated_at",
            "start_param": "since",
            "cursor_type": "integer",
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        source.source_for_pipeline(config, inputs)

        threaded_incremental = mock_resources.call_args.args[0]["resources"][0]["endpoint"]["incremental"]
        assert threaded_incremental == {"cursor_path": "updated_at", "start_param": "since"}


class TestCustomSourceNonRetryableErrors(SimpleTestCase):
    def test_missing_resource_message_is_classified_non_retryable(self):
        # The message `source_for_pipeline` raises when a schema points to a resource
        # the manifest no longer defines must be recognized by the source's classifier,
        # so `_handle_import_error` stops the job instead of capturing + retrying it.
        # Pin the specific substring on both ends — the raised message and the dict key —
        # so the guard breaks if either the wording or the key drifts.
        with self.assertRaises(ValueError) as ctx:
            _fanout_chain(_minimal_manifest(), "nonexistent")

        assert "not found in config" in str(ctx.exception)
        assert "not found in config" in CustomSource().get_non_retryable_errors()

    @parameterized.expand(["invalid_client", "invalid_grant"])
    def test_oauth2_permanent_errors_are_classified_non_retryable(self, error_code):
        # A permanent OAuth2 token rejection (invalid_client / invalid_grant) surfaces the
        # standard error code in OAuth2Auth's failure message, and the classifier matches that
        # substring so the job fails fast instead of burning its whole retry budget.
        non_retryable = CustomSource().get_non_retryable_errors()
        assert error_code in non_retryable
        message = OAuth2AuthRequestError(
            f"HTTP 401 from the OAuth2 token endpoint: {error_code}: nope", error_code=error_code, is_permanent=True
        )
        assert any(key in str(message) for key in non_retryable)


def _fanout_manifest() -> dict:
    """A parent (`forms`) + fan-out child (`responses`) that binds the parent's
    `id` into its path via a `type: "resolve"` param."""
    return {
        "client": {"base_url": "https://api.example.com", "auth": {"type": "bearer"}},
        "resources": [
            {"name": "forms", "primary_key": "id", "endpoint": {"path": "/forms", "data_selector": "items"}},
            {
                "name": "responses",
                "primary_key": "token",
                "endpoint": {
                    "path": "/forms/{form_id}/responses",
                    "data_selector": "items",
                    "params": {"form_id": {"type": "resolve", "resource": "forms", "field": "id"}},
                },
            },
        ],
    }


def _fake_resource(name: str) -> MagicMock:
    # MagicMock(name=...) sets the mock's repr, not a `.name` attribute, so the
    # source's `r.name == chosen_name` lookup needs the attribute set explicitly.
    resource = MagicMock()
    resource.name = name
    return resource


class _PageResource:
    """Iterable stand-in for an engine Resource: yields preset pages (list[dict]),
    applying any registered ``add_filter`` predicates so the preview's parent cap
    is exercised the same way the real Resource would apply it."""

    def __init__(self, name: str, pages: list[list[dict[str, Any]]]) -> None:
        self.name = name
        self._pages = pages
        self._filters: list[Any] = []

    def add_filter(self, fn: Any) -> "_PageResource":
        self._filters.append(fn)
        return self

    def __iter__(self) -> Any:
        for page in self._pages:
            yield [item for item in page if all(f(item) for f in self._filters)]


class _CountingResource:
    """Engine Resource that yields one-row pages lazily and records how many rows
    it produced, so a test can prove preview abandons the generator at the cap
    instead of draining it."""

    def __init__(self, name: str, total_rows: int) -> None:
        self.name = name
        self.total_rows = total_rows
        self.produced = 0

    def __iter__(self) -> Any:
        for index in range(self.total_rows):
            self.produced = index + 1
            yield [{"id": index}]


def _break_unknown_parent(m: dict) -> None:
    m["resources"][1]["endpoint"]["params"]["form_id"]["resource"] = "nonexistent"


def _break_resolve_not_in_path(m: dict) -> None:
    # Resolve param with no matching `{placeholder}` — the engine can only inject into the path.
    m["resources"][1]["endpoint"]["path"] = "/responses"


def _break_cycle(m: dict) -> None:
    # Make `forms` depend on `responses`, closing a loop.
    m["resources"][0]["endpoint"]["path"] = "/forms/{response_token}"
    m["resources"][0]["endpoint"]["params"] = {
        "response_token": {"type": "resolve", "resource": "responses", "field": "token"}
    }


def _break_multiple_resolve_params(m: dict) -> None:
    m["resources"][1]["endpoint"]["path"] = "/forms/{form_id}/responses/{other_id}"
    m["resources"][1]["endpoint"]["params"]["other_id"] = {"type": "resolve", "resource": "forms", "field": "id"}


def _break_missing_resolve_field(m: dict) -> None:
    # The engine raises KeyError (not ValueError) for this shape — it must still
    # surface as a clean validation error, not a 500.
    del m["resources"][1]["endpoint"]["params"]["form_id"]["field"]


def _break_missing_resolve_resource(m: dict) -> None:
    del m["resources"][1]["endpoint"]["params"]["form_id"]["resource"]


def _break_invalid_resolve_field_jsonpath(m: dict) -> None:
    # The resolve field is a JSONPath; a malformed one raises a bare-Exception
    # subclass (JsonPathParserError) from inside the engine.
    m["resources"][1]["endpoint"]["params"]["form_id"]["field"] = "user..["


def _break_path_starting_with_placeholder(m: dict) -> None:
    # A child path that BEGINS with the parent placeholder lets an absolute URL
    # in the parent's field move the authenticated request off base_url.
    m["resources"][1]["endpoint"]["path"] = "{form_id}/responses"


def _break_leading_slash_placeholder(m: dict) -> None:
    # A leading slash is NOT a defense: the engine strips leading slashes before
    # joining onto base_url, so `/{form_id}/...` still resolves to whatever host
    # the bound parent value carries.
    m["resources"][1]["endpoint"]["path"] = "/{form_id}/responses"


def _break_scheme_prefixed_placeholder(m: dict) -> None:
    # A literal scheme prefix lets the placeholder supply the URL's authority:
    # `https:{form_id}/...` with `form_id="//attacker/x"` formats to
    # `https://attacker/x/...`, an absolute URL off base_url. The placeholder is
    # not the first path segment, so a position-only guard misses it.
    m["resources"][1]["endpoint"]["path"] = "https:{form_id}/responses"


def _add_nested_child(m: dict) -> None:
    # Grandchild: nesting is capped at one level — a parent must be top-level.
    m["resources"].append(
        {
            "name": "answers",
            "primary_key": "id",
            "endpoint": {
                "path": "/responses/{response_token}/answers",
                "params": {"response_token": {"type": "resolve", "resource": "responses", "field": "token"}},
            },
        }
    )


class TestCustomSourceFanoutValidation(SimpleTestCase):
    def test_accepts_valid_fanout(self):
        validate_manifest(_fanout_manifest())

    @parameterized.expand(
        [
            ("unknown_parent", _break_unknown_parent),
            ("resolve_param_not_bound_in_path", _break_resolve_not_in_path),
            ("cycle", _break_cycle),
            ("multiple_resolve_params", _break_multiple_resolve_params),
            ("missing_resolve_field", _break_missing_resolve_field),
            ("missing_resolve_resource", _break_missing_resolve_resource),
            ("invalid_resolve_field_jsonpath", _break_invalid_resolve_field_jsonpath),
            ("nested_child", _add_nested_child),
            ("path_starting_with_placeholder", _break_path_starting_with_placeholder),
            ("leading_slash_placeholder", _break_leading_slash_placeholder),
            ("scheme_prefixed_placeholder", _break_scheme_prefixed_placeholder),
        ]
    )
    def test_rejects_invalid_fanout(self, _name, break_manifest):
        # Every fan-out misconfiguration the engine's dependency graph rejects must
        # surface at manifest-validation time, not first sync.
        manifest = _fanout_manifest()
        break_manifest(manifest)
        with self.assertRaises(ManifestValidationError):
            validate_manifest(manifest)

    @parameterized.expand(
        [
            # str(graphlib.CycleError) is its raw args tuple — the user-facing
            # message must render the cycle, not the tuple repr.
            ("cycle", _break_cycle, ["dependency cycle"]),
            # The nesting cap must name the offending resources.
            ("nested_child", _add_nested_child, ["'answers'", "'responses'", "one level of nesting"]),
            # The placeholder-authority guard must name the resource and point at
            # the scheme-prefix escape, not just the leading-segment case.
            ("scheme_prefixed_placeholder", _break_scheme_prefixed_placeholder, ["'responses'", "scheme", "redirect"]),
        ]
    )
    def test_rejection_message_is_readable(self, _name, break_manifest, expected_fragments):
        manifest = _fanout_manifest()
        break_manifest(manifest)
        with self.assertRaises(ManifestValidationError) as ctx:
            validate_manifest(manifest)
        message = str(ctx.exception)
        assert not message.startswith("(")
        for fragment in expected_fragments:
            assert fragment in message

    @parameterized.expand(
        [
            # Graph rules apply on every validation path — create/update ...
            ("create_or_update", {}),
            # ... and schema-scoped read checks against stored config alike.
            # Builder-authored manifests are always graph-valid, so a stored
            # manifest tripping this was hand-authored JSON that never synced.
            ("schema_scoped_read_check", {"schema_name": "forms"}),
        ]
    )
    def test_validate_credentials_rejects_broken_graph(self, _name, kwargs):
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999, **kwargs)
        assert ok is False
        assert err is not None and "nonexistent" in err


class TestFanoutChain(SimpleTestCase):
    def test_top_level_resource_has_no_ancestors(self):
        manifest = _fanout_manifest()
        chain = _fanout_chain(manifest, "forms")
        assert chain == FanoutChain(ancestors=[], child=manifest["resources"][0])
        assert chain.is_fanout_child is False

    def test_child_chain_is_parent_first(self):
        manifest = _fanout_manifest()
        parent, child = manifest["resources"]
        chain = _fanout_chain(manifest, "responses")
        assert chain == FanoutChain(ancestors=[parent], child=child)
        assert chain.is_fanout_child is True

    def test_multi_level_chain(self):
        # Create-time validation rejects nesting beyond one level, but the sync
        # path must still walk a deeper chain correctly if a stored manifest
        # carries one (e.g. written before the cap existed).
        manifest = _fanout_manifest()
        _add_nested_child(manifest)
        forms, responses, answers = manifest["resources"]
        assert _fanout_chain(manifest, "answers") == FanoutChain(ancestors=[forms, responses], child=answers)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.logger")
    def test_falls_back_to_chosen_when_unrelated_resource_breaks_the_graph(self, mock_logger):
        # A stored manifest can predate the create-time graph rules. A graph
        # error on a sibling must not sink this schema — the chain degrades to
        # the pre-fan-out single-resource behavior, and the degradation is
        # logged so the affected population stays measurable.
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)
        manifest["resources"].append(
            {"name": "users", "primary_key": "id", "endpoint": {"path": "/users", "data_selector": "items"}}
        )
        assert _fanout_chain(manifest, "users") == FanoutChain(ancestors=[], child=manifest["resources"][2])
        mock_logger.warning.assert_called_once()
        assert mock_logger.warning.call_args.args[0] == "custom_source_fanout_graph_fallback"
        assert mock_logger.warning.call_args.kwargs["schema_name"] == "users"

    def test_raises_for_chosen_resource_in_a_cycle(self):
        # The graph builder itself doesn't reject cycles (only create-time
        # static_order does) — the walk must fail loudly, not loop or truncate.
        manifest = _fanout_manifest()
        _break_cycle(manifest)
        with self.assertRaises(ValueError):
            _fanout_chain(manifest, "responses")


class TestCustomSourceFanoutPipeline(SimpleTestCase):
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_child_schema_runs_parent_and_child(self, mock_resources):
        # Selecting the child must hand the engine BOTH resources (parent first)
        # and return only the child resource — the parent is fetched transiently.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        threaded_resources = mock_resources.call_args.args[0]["resources"]
        assert [r["name"] for r in threaded_resources] == ["forms", "responses"]
        assert cast(Any, response.items()).name == "responses"
        assert response.primary_keys == ["token"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_top_level_schema_runs_only_that_resource(self, mock_resources):
        # A parent selected on its own is a one-element chain — only that resource
        # reaches the engine (no ancestors), and it's returned by name.
        mock_resources.return_value = [_fake_resource("forms")]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()))
        inputs = MagicMock(
            team_id=999,
            schema_name="forms",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        assert [r["name"] for r in mock_resources.call_args.args[0]["resources"]] == ["forms"]
        assert cast(Any, response.items()).name == "forms"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_strips_incremental_from_parent_but_keeps_child(self, mock_resources):
        # The run's high-watermark belongs to the child; applying it to the parent
        # would silently drop parents (and their children). Parent must full-scan.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        manifest["resources"][0]["endpoint"]["incremental"] = {"cursor_path": "updated_at", "start_param": "since"}
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        source.source_for_pipeline(config, inputs)

        parent_cfg, child_cfg = mock_resources.call_args.args[0]["resources"]
        assert "incremental" not in parent_cfg["endpoint"]
        assert child_cfg["endpoint"]["incremental"] == {"cursor_path": "submitted_at", "start_param": "since"}
        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] == "2024-01-01T00:00:00Z"

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_strips_cursor_type_from_child(self, mock_resources):
        # cursor_type is a schema-typing hint the engine's Incremental(**config)
        # rejects — it must be removed before the child reaches the engine.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        manifest["resources"][1]["endpoint"]["incremental"] = {
            "cursor_path": "submitted_at",
            "start_param": "since",
            "cursor_type": "datetime",
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        source.source_for_pipeline(config, inputs)

        _parent_cfg, child_cfg = mock_resources.call_args.args[0]["resources"]
        assert child_cfg["endpoint"]["incremental"] == {"cursor_path": "submitted_at", "start_param": "since"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_strips_params_style_incremental_from_parent(self, mock_resources):
        # The engine also builds an incremental tracker from a params-style
        # {"type": "incremental"} spec — it must be stripped from ancestors too,
        # or the child's watermark would be injected as the parent's start param.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        manifest["resources"][0]["endpoint"]["params"] = {
            "since": {"type": "incremental", "cursor_path": "updated_at"},
            "status": "active",
        }
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2024-01-01T00:00:00Z",
        )
        source.source_for_pipeline(config, inputs)

        parent_cfg, _child_cfg = mock_resources.call_args.args[0]["resources"]
        # Static params survive; only the incremental spec is removed.
        assert parent_cfg["endpoint"]["params"] == {"status": "active"}

    @parameterized.expand(
        [
            # Child with no declared sort_mode -> forced "desc".
            ("child_default", "responses", None, "desc"),
            # Child that explicitly declares "asc" -> STILL forced "desc". This is
            # the override that matters: per-batch asc commits on a child would
            # advance the watermark past later parents' older rows and skip them.
            ("child_overrides_declared_asc", "responses", "asc", "desc"),
            # Top-level resource keeps its declaration (default "asc").
            ("parent_keeps_declared", "forms", None, "asc"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_child_forces_deferred_watermark_sort_mode(
        self, _name, schema_name, declared_sort_mode, expected, mock_resources
    ):
        # Fan-out child rows arrive grouped per parent, never globally
        # cursor-ascending, so the "asc" per-batch watermark commit would skip
        # later parents' older rows after an interruption — children must always
        # use the deferred-commit ("desc") behavior.
        mock_resources.return_value = [_fake_resource("forms"), _fake_resource("responses")]
        manifest = _fanout_manifest()
        if declared_sort_mode is not None:
            next(r for r in manifest["resources"] if r["name"] == schema_name)["sort_mode"] = declared_sort_mode
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name=schema_name,
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)
        assert response.sort_mode == expected

    def test_engine_config_error_raises_non_retryable(self):
        # include_from_parent without a resolve param passes create-time graph
        # validation but is rejected by the engine at build time — a deterministic
        # config error that must not burn the Temporal retry budget.
        manifest = _minimal_manifest()
        manifest["resources"][0]["include_from_parent"] = ["id"]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_broken_sibling_does_not_sink_healthy_schema_sync(self, mock_resources):
        # A stored manifest can carry a graph-broken resource from before the
        # create-time rules existed — its healthy schemas must keep syncing.
        mock_resources.return_value = [_fake_resource("forms")]
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="forms",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        assert [r["name"] for r in mock_resources.call_args.args[0]["resources"]] == ["forms"]
        assert cast(Any, response.items()).name == "forms"

    def test_broken_sibling_fails_child_schema_fast(self):
        # Accepted trade-off: a child schema can't be built without the graph,
        # so when an UNRELATED resource breaks the graph, the fallback hands the
        # engine just the child, whose orphaned resolve param the engine rejects
        # at build time — a loud, non-retryable failure rather than wrong data.
        # (Top-level siblings keep syncing; see
        # test_broken_sibling_does_not_sink_healthy_schema_sync.)
        manifest = _fanout_manifest()
        manifest["resources"].append(
            {
                "name": "broken",
                "primary_key": "id",
                "endpoint": {
                    "path": "/broken/{x}",
                    "params": {"x": {"type": "resolve", "resource": "nonexistent", "field": "id"}},
                },
            }
        )

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        with self.assertRaises(NonRetryableException):
            source.source_for_pipeline(config, inputs)

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    )
    def test_fanout_runs_through_real_engine(self, mock_make_session):
        # End-to-end through the real REST engine (only the HTTP session is
        # mocked): the parent is fetched once, the child is requested per parent
        # row, and `include_from_parent` carries the parent id onto each child row.
        def _response(body: dict) -> Response:
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps(body).encode()
            resp.headers["Content-Type"] = "application/json"
            return resp

        session = mock_make_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = [
            _response({"items": [{"id": "f1"}, {"id": "f2"}]}),  # GET /forms
            _response({"items": [{"token": "r1"}, {"token": "r2"}]}),  # GET /forms/f1/responses
            _response({"items": [{"token": "r3"}]}),  # GET /forms/f2/responses
        ]

        manifest = _fanout_manifest()
        for resource in manifest["resources"]:
            resource["endpoint"]["paginator"] = {"type": "single_page"}
        manifest["resources"][1]["include_from_parent"] = ["id"]

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=999,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )
        response = source.source_for_pipeline(config, inputs)

        rows = [row for page in cast(Any, response.items()) for row in page]
        assert [row["token"] for row in rows] == ["r1", "r2", "r3"]
        # include_from_parent injects the parent id as `_<parent>_<field>`.
        assert [row["_forms_id"] for row in rows] == ["f1", "f1", "f2"]
        requested_paths = [call.args[0].url for call in session.prepare_request.call_args_list]
        assert requested_paths == [
            "https://api.example.com/forms",
            "https://api.example.com/forms/f1/responses",
            "https://api.example.com/forms/f2/responses",
        ]


class TestCustomSourceFanoutSchemasAndProbe(SimpleTestCase):
    def test_child_resource_is_its_own_schema(self):
        manifest = _fanout_manifest()
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schemas = {s.name: s for s in source.get_schemas(config, team_id=999)}

        assert set(schemas) == {"forms", "responses"}
        assert schemas["responses"].supports_incremental is True
        assert [f["field"] for f in schemas["responses"].incremental_fields] == ["submitted_at"]

    def test_broken_graph_does_not_break_schema_listing(self):
        # Schema listing runs on stored manifests; a graph error (which the
        # create-time validation now rejects, but older manifests may carry)
        # must not make it raise.
        manifest = _fanout_manifest()
        _break_unknown_parent(manifest)

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        schemas = {s.name for s in source.get_schemas(config, team_id=999)}
        assert schemas == {"forms", "responses"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.make_tracked_session")
    def test_probe_skips_fanout_child(self, mock_session):
        # The child can't be probed without a parent row, so only the parent is hit.
        mock_session.return_value.request.return_value = MagicMock(status_code=200, text="{}")

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok, err

        probed_urls = [call.args[1] for call in mock_session.return_value.request.call_args_list]
        assert probed_urls == ["https://api.example.com/forms"]


class TestCustomSourceIncrementalDatetimeFormat(SimpleTestCase):
    def _manifest(self, datetime_format=None) -> dict:
        manifest = _minimal_manifest()
        incremental = {"cursor_path": "updated_at", "start_param": "since"}
        if datetime_format is not None:
            incremental["datetime_format"] = datetime_format
        manifest["resources"][0]["endpoint"]["incremental"] = incremental
        return manifest

    def _run(self, manifest, watermark):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=1,
            schema_name="users",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        source.source_for_pipeline(config, inputs)

    _DT = datetime(2026, 6, 8, 12, 53, 34, tzinfo=UTC)

    @parameterized.expand(
        [
            ("typeform_z", "%Y-%m-%dT%H:%M:%SZ", _DT, "2026-06-08T12:53:34Z"),
            ("date_only", "%Y-%m-%d", _DT, "2026-06-08"),
            ("space_separated", "%Y-%m-%d %H:%M:%S", _DT, "2026-06-08 12:53:34"),
            ("iso8601_default", None, _DT, "2026-06-08T12:53:34+00:00"),
            ("string_passthrough", "%Y-%m-%dT%H:%M:%SZ", "2026-06-08T00:00:00Z", "2026-06-08T00:00:00Z"),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_datetime_watermark_formatting(self, _name, fmt, watermark, expected, mock_resources):
        mock_resources.return_value = [_fake_resource("users")]
        self._run(self._manifest(fmt), watermark)

        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] == expected
        incremental = mock_resources.call_args.args[0]["resources"][0]["endpoint"]["incremental"]
        assert "datetime_format" not in incremental

    @parameterized.expand([("integer", 123), ("object", {"format": "%Y"}), ("list", ["%Y"])])
    def test_non_string_format_raises_non_retryable(self, _name, fmt):
        with self.assertRaises(NonRetryableException) as ctx:
            self._run(self._manifest(fmt), self._DT)
        assert "datetime_format" in str(ctx.exception)

    @parameterized.expand([("integer", 123), ("object", {"format": "%Y"})])
    def test_non_string_format_rejected_at_validation(self, _name, fmt):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(self._manifest(fmt)), auth_token="abc")
        ok, err = source.validate_credentials(config, team_id=999)
        assert ok is False
        assert err is not None and "datetime_format" in err and "'users'" in err

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
    )
    def test_datetime_format_reaches_request_through_real_engine(self, mock_make_session):
        def _response(body: dict) -> Response:
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps(body).encode()
            resp.headers["Content-Type"] = "application/json"
            return resp

        captured: list[dict] = []

        def send(prepared, **kwargs):
            captured.append(dict(getattr(prepared, "params", {}) or {}))
            if "/forms/f1/responses" in prepared.url:
                return _response({"items": []})
            return _response({"items": [{"id": "f1"}]})

        session = mock_make_session.return_value
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = send

        manifest = _fanout_manifest()
        for resource in manifest["resources"]:
            resource["endpoint"]["paginator"] = {"type": "single_page"}
        manifest["resources"][1]["endpoint"]["incremental"] = {
            "cursor_path": "submitted_at",
            "start_param": "since",
            "datetime_format": "%Y-%m-%dT%H:%M:%SZ",
        }

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest))
        inputs = MagicMock(
            team_id=1,
            schema_name="responses",
            job_id="job-1",
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 6, 8, 12, 53, 34, tzinfo=UTC),
        )
        list(cast(Any, source.source_for_pipeline(config, inputs).items()))

        child_params = next((p for p in captured if "since" in p), {})
        assert child_params.get("since") == "2026-06-08T12:53:34Z"


def _apikey_manifest() -> dict:
    """A minimal manifest whose auth is an api_key in a query param, so the
    injected secret is registered for value-based redaction."""
    manifest = _minimal_manifest()
    manifest["client"]["auth"] = {"type": "api_key", "name": "key", "location": "query"}
    return manifest


class TestPreviewSession(SimpleTestCase):
    def test_send_pins_no_redirect_streams_and_default_timeout(self):
        prepared = requests.Request("GET", "https://acme.example.com/").prepare()
        response = Response()
        response.status_code = 200
        response.raw = MagicMock()
        response.raw.stream.return_value = iter([b"{}"])

        with patch.object(requests.Session, "send", return_value=response) as parent_send:
            _PreviewSession().send(prepared)

        forwarded = parent_send.call_args.kwargs
        assert forwarded["allow_redirects"] is False
        assert forwarded["stream"] is True
        assert forwarded["timeout"] == (PROBE_CONNECT_TIMEOUT, PROBE_READ_TIMEOUT)


class TestJsonTypeLabel(SimpleTestCase):
    @parameterized.expand(
        [
            ("null", None, "null"),
            ("boolean", True, "boolean"),
            ("integer", 7, "integer"),
            ("number", 1.5, "number"),
            ("string", "x", "string"),
            ("array", [1, 2], "array"),
            ("object", {"k": 1}, "object"),
            ("unknown_falls_back_to_string", (1, 2), "string"),
        ]
    )
    def test_labels_each_json_type(self, _name, value, expected):
        assert _json_type_label(value) == expected


class TestCustomSourcePreviewResource(SimpleTestCase):
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_returns_rows_and_inferred_columns(self, mock_resources):
        mock_resources.return_value = [
            _PageResource("users", [[{"id": 1, "name": "a", "active": True}, {"id": 2, "name": "b", "active": None}]])
        ]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        result = source.preview_resource(config, team_id=999, resource_name="users")

        assert result.error is None
        assert result.row_count == 2
        assert result.rows[0]["id"] == 1
        assert {column["name"]: column["type"] for column in result.columns} == {
            "id": "integer",
            "name": "string",
            "active": "boolean",
        }

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_column_type_uses_first_non_null_value(self, mock_resources):
        mock_resources.return_value = [_PageResource("users", [[{"score": None}, {"score": 7}]])]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        result = source.preview_resource(config, team_id=999, resource_name="users")

        assert {column["name"]: column["type"] for column in result.columns} == {"score": "integer"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_row_cap_stops_generator_early(self, mock_resources):
        resource = _CountingResource("users", total_rows=100)
        mock_resources.return_value = [resource]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        result = source.preview_resource(config, team_id=999, resource_name="users", max_rows=5)

        assert result.row_count == 5
        assert resource.produced == 5

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_max_rows_clamped_to_hard_cap(self, mock_resources):
        one_big_page = [[{"id": index} for index in range(PREVIEW_MAX_ROWS + 50)]]
        mock_resources.return_value = [_PageResource("users", one_big_page)]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        result = source.preview_resource(config, team_id=999, resource_name="users", max_rows=PREVIEW_MAX_ROWS + 50)

        assert result.row_count == PREVIEW_MAX_ROWS

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_engine_manifest_is_single_page_incremental_stripped_session_injected(self, mock_resources):
        mock_resources.return_value = [_PageResource("users", [[]])]
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["incremental"] = {"cursor_path": "updated_at", "start_param": "since"}
        manifest["resources"][0]["endpoint"]["paginator"] = {"type": "offset", "limit": 100}
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        source.preview_resource(config, team_id=999, resource_name="users")

        engine_manifest = mock_resources.call_args.args[0]
        endpoint = engine_manifest["resources"][0]["endpoint"]
        assert endpoint["paginator"] == {"type": "single_page"}
        assert "incremental" not in endpoint
        assert isinstance(engine_manifest["client"]["session"], _PreviewSession)
        assert engine_manifest["client"]["max_retries"] == 1
        assert mock_resources.call_args.kwargs["db_incremental_field_last_value"] is None

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._is_host_safe",
        return_value=(False, "blocked: internal host"),
    )
    def test_rejects_unsafe_host(self, _mock):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        with self.assertRaises(ManifestValidationError):
            source.preview_resource(config, team_id=999, resource_name="users")

    def test_unknown_resource_raises_value_error(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="abc")
        with self.assertRaises(ValueError):
            source.preview_resource(config, team_id=999, resource_name="does_not_exist")

    def test_invalid_json_raises_manifest_validation_error(self):
        source = CustomSource()
        config = CustomSourceConfig(manifest_json="{not json}")
        with self.assertRaises(ManifestValidationError):
            source.preview_resource(config, team_id=999, resource_name="users")

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_fanout_child_runs_ancestors_full_scan(self, mock_resources):
        mock_resources.return_value = [
            _PageResource("forms", [[{"id": 1}]]),
            _PageResource("responses", [[{"token": "t1"}]]),
        ]
        manifest = _fanout_manifest()
        manifest["resources"][0]["endpoint"]["incremental"] = {"cursor_path": "updated_at", "start_param": "since"}
        manifest["resources"][1]["endpoint"]["incremental"] = {"cursor_path": "submitted_at", "start_param": "since"}
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        result = source.preview_resource(config, team_id=999, resource_name="responses")

        engine_resources = mock_resources.call_args.args[0]["resources"]
        assert [resource["name"] for resource in engine_resources] == ["forms", "responses"]
        for resource in engine_resources:
            assert "incremental" not in resource["endpoint"]
            assert resource["endpoint"]["paginator"] == {"type": "single_page"}
        assert result.rows == [{"token": "t1"}]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._build_preview_session")
    def test_fanout_empty_child_caps_parent_requests_through_real_engine(self, mock_build_session):
        # End-to-end through the real engine: a parent page far larger than the cap,
        # every child resolving empty. Empty child pages are dropped before the row
        # reader sees them, so only the parent cap keeps the per-parent child requests
        # bounded — the regression a fake-page stand-in can't catch.
        def _response(body: dict) -> Response:
            resp = Response()
            resp.status_code = 200
            resp._content = json.dumps(body).encode()
            resp.headers["Content-Type"] = "application/json"
            return resp

        sent_urls: list[str] = []

        def _send(prepared):
            sent_urls.append(prepared.url)
            if prepared.url.endswith("/forms"):
                return _response({"items": [{"id": f"f{index}"} for index in range(PREVIEW_MAX_FANOUT_PARENTS + 20)]})
            return _response({"items": []})

        session = MagicMock()
        session.headers = {}
        session.prepare_request.side_effect = lambda request: request
        session.send.side_effect = _send
        mock_build_session.return_value = session

        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_fanout_manifest()), auth_token="abc")
        result = source.preview_resource(config, team_id=999, resource_name="responses")

        assert result.row_count == 0
        child_requests = [url for url in sent_urls if "/responses" in url]
        assert len(child_requests) == PREVIEW_MAX_FANOUT_PARENTS

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source._is_host_safe",
        side_effect=lambda hostname, team_id: (hostname == "api.example.com", "blocked: internal host"),
    )
    def test_rejects_resource_resolving_to_new_internal_host(self, _mock_safe, mock_resources):
        manifest = _minimal_manifest()
        manifest["resources"][0]["endpoint"]["path"] = "https://169.254.169.254/users"
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(manifest), auth_token="abc")
        with self.assertRaises(ManifestValidationError):
            source.preview_resource(config, team_id=999, resource_name="users")

        mock_resources.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_live_fetch_error_is_returned_and_secret_redacted(self, mock_resources):
        class _Boom:
            name = "users"

            def __iter__(self) -> Any:
                raise RuntimeError("connect failed for https://api.example.com/users?key=supersecret")

        mock_resources.return_value = [_Boom()]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_apikey_manifest()), auth_api_key="supersecret")
        result = source.preview_resource(config, team_id=999, resource_name="users")

        assert result.rows == []
        assert result.row_count == 0
        assert result.error is not None
        assert "supersecret" not in result.error
        assert "***" in result.error

    def test_redact_secrets_redacts_url_encoded_credential(self):
        secret = "ab/cd+ef=gh"
        text = f"HTTPError for https://api.example.com/users?key={quote(secret, safe='')}"
        redacted = _redact_secrets(text, (secret,))

        assert quote(secret, safe="") not in redacted
        assert "***" in redacted

    @staticmethod
    def _streamed_response(body_size: int) -> Response:
        # raw.stream(amt) yields the decoded body in <=amt-byte chunks, like urllib3.
        response = Response()
        response.status_code = 200
        response.raw = MagicMock()
        payload = b"x" * body_size
        response.raw.stream.side_effect = lambda amt, **kwargs: (
            payload[i : i + amt] for i in range(0, len(payload), amt)
        )
        return response

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.PREVIEW_READ_CHUNK_BYTES", 16
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.PREVIEW_MAX_TOTAL_BODY_BYTES",
        100,
    )
    def test_preview_session_aborts_oversized_body_without_full_read(self):
        # A body far over budget must raise AND stop mid-stream — never inflate the
        # whole thing (the failure mode of a single decode-everything read).
        yielded = {"chunks": 0}

        def stream(amt, **kwargs):
            for _ in range(100):
                yielded["chunks"] += 1
                yield b"x" * amt

        response = Response()
        response.status_code = 200
        response.raw = MagicMock()
        response.raw.stream.side_effect = stream
        with patch.object(requests.Session, "send", return_value=response):
            with self.assertRaises(PreviewResponseTooLargeError):
                _PreviewSession().send(MagicMock())

        assert yielded["chunks"] <= 100 // 16 + 1

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.PREVIEW_READ_CHUNK_BYTES", 16
    )
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.PREVIEW_MAX_TOTAL_BODY_BYTES",
        100,
    )
    def test_preview_session_enforces_budget_across_requests(self):
        # Each response is under the budget on its own, but together they exceed it:
        # the budget is the whole preview's, not per response.
        responses = [self._streamed_response(60), self._streamed_response(60)]
        with patch.object(requests.Session, "send", side_effect=responses):
            session = _PreviewSession()
            session.send(MagicMock())
            with self.assertRaises(PreviewResponseTooLargeError):
                session.send(MagicMock())

    def test_preview_session_returns_capped_body(self):
        body = b'{"items": [{"id": 1}]}'
        within_cap = Response()
        within_cap.status_code = 200
        within_cap.raw = MagicMock()
        within_cap.raw.stream.side_effect = lambda amt, **kwargs: (body[i : i + amt] for i in range(0, len(body), amt))
        with patch.object(requests.Session, "send", return_value=within_cap):
            response = _PreviewSession().send(MagicMock())

        assert response.json() == {"items": [{"id": 1}]}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.custom.source.rest_api_resources")
    def test_credential_never_appears_in_result(self, mock_resources):
        mock_resources.return_value = [_PageResource("users", [[{"id": 1}]])]
        source = CustomSource()
        config = CustomSourceConfig(manifest_json=json.dumps(_minimal_manifest()), auth_token="topsecret-token")
        result = source.preview_resource(config, team_id=999, resource_name="users")

        assert "topsecret-token" not in json.dumps(result._asdict())


def _classify_non_retryable(error: Exception) -> bool:
    """Replicate the pipeline's sync-time non-retryable check (substring match on str(error))."""
    non_retryable_errors = CustomSource().get_non_retryable_errors()
    return any(key in str(error) for key in non_retryable_errors)


class TestCustomSourceOAuth2NonRetryableClassification(SimpleTestCase):
    @parameterized.expand(
        [
            # A token-endpoint failure that carries no standard OAuth error code (a bare 4xx body or
            # an unfollowed 3xx redirect) used to slip past the old invalid_client/invalid_grant-only
            # match and retry until the activity budget was exhausted. Drive it through the real raise.
            ("redirect_302", 302, {}),
            ("bare_400_no_error_code", 400, {}),
            # OAuth error codes other than invalid_client/invalid_grant — also permanent, also missed
            # before. Run them through the real _extract_token_error path.
            ("unauthorized_client", 400, {"error": "unauthorized_client"}),
            ("unsupported_grant_type", 400, {"error": "unsupported_grant_type"}),
            ("invalid_scope", 400, {"error": "invalid_scope"}),
            ("invalid_request", 400, {"error": "invalid_request"}),
        ]
    )
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_permanent_token_status_errors_classified_non_retryable(self, _name, status_code, payload, mock_session):
        response = MagicMock(status_code=status_code)
        response.raw.read.return_value = json.dumps(payload).encode()
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert ctx.exception.is_permanent
        assert _classify_non_retryable(ctx.exception), str(ctx.exception)

    @parameterized.expand(
        [
            # Malformed/unexpected token responses raise permanent errors whose messages share no
            # phrase with the status-code path — the marker is what makes them all classifiable.
            ("non_json_body", "non_json"),
            ("non_dict_body", [1, 2, 3]),
            ("missing_access_token", {"expires_in": 60}),
        ]
    )
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_permanent_token_response_errors_classified_non_retryable(self, _name, body, mock_session):
        response = MagicMock(status_code=200)
        if body == "non_json":
            response.raw.read.return_value = b"not json"
        else:
            response.raw.read.return_value = json.dumps(body).encode()
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert ctx.exception.is_permanent
        assert _classify_non_retryable(ctx.exception), str(ctx.exception)

    @parameterized.expand(
        [
            # The original two codes still match (their dedicated copy is retained).
            ("invalid_client", 401, {"error": "invalid_client"}),
            ("invalid_grant", 400, {"error": "invalid_grant"}),
        ]
    )
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_known_oauth_codes_still_classified_non_retryable(self, _name, status_code, payload, mock_session):
        response = MagicMock(status_code=status_code)
        response.raw.read.return_value = json.dumps(payload).encode()
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert _classify_non_retryable(ctx.exception), str(ctx.exception)

    @parameterized.expand(
        [
            # Transient (429 / 5xx) token errors must stay retryable — the marker is absent, so they
            # must NOT match. Guards the fix from over-matching the shared token-endpoint phrasing.
            ("rate_limited_429", 429, {"error": "slow_down"}),
            ("server_error_503", 503, {}),
        ]
    )
    @patch(f"{AUTH_MODULE}.make_tracked_session")
    def test_transient_token_errors_stay_retryable(self, _name, status_code, payload, mock_session):
        response = MagicMock(status_code=status_code)
        response.raw.read.return_value = json.dumps(payload).encode()
        mock_session.return_value.post.return_value = response
        auth = OAuth2Auth(token_url="https://a/t", client_id="cid", client_secret="cs")
        with self.assertRaises(OAuth2AuthRequestError) as ctx:
            auth._obtain_token()
        assert not ctx.exception.is_permanent
        assert OAUTH2_PERMANENT_ERROR_MARKER not in str(ctx.exception)
        assert not _classify_non_retryable(ctx.exception), str(ctx.exception)
