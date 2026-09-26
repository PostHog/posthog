import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import ConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify import (
    CoolifyHostNotAllowedError,
    _client_config,
    api_base_url,
    coolify_source,
    hostname_of,
    normalize_base_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.settings import (
    COOLIFY_ENDPOINTS,
    DEPLOYMENTS_PAGE_SIZE,
)

BASE_URL = "https://coolify.example.com"
API_BASE = f"{BASE_URL}/api/v1"
APP_UUID = "o8g80wkc4s0gks0k0ok8cog4"


def _make_response(json_body: Any = None, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp.headers["Content-Type"] = "application/json"
    resp._content = json.dumps(json_body if json_body is not None else {}).encode()
    return resp


def _rows(endpoint: str, base_url: str = BASE_URL) -> list[dict[str, Any]]:
    resource = coolify_source(base_url, "coolify-token", endpoint, team_id=1, job_id="job-1")
    return [row for page in resource for row in page]


class TestCoolifyNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            pytest.param("https://coolify.example.com", BASE_URL, id="already_normalized"),
            pytest.param("https://coolify.example.com/", BASE_URL, id="trailing_slash"),
            pytest.param("https://coolify.example.com/api/v1", BASE_URL, id="pasted_api_base"),
            pytest.param("https://coolify.example.com/api/v1/", BASE_URL, id="pasted_api_base_with_slash"),
            pytest.param("coolify.example.com", BASE_URL, id="bare_host_gets_https"),
            pytest.param("  https://coolify.example.com  ", BASE_URL, id="surrounding_whitespace"),
        ],
    )
    def test_resolves_pasted_variants_to_one_instance_root(self, raw: str, expected: str) -> None:
        # Users paste the URL from a browser bar or the API docs; every variant must produce the
        # same request URLs or a pasted `/api/v1` suffix silently doubles into `/api/v1/api/v1`.
        assert normalize_base_url(raw) == expected
        assert api_base_url(raw) == f"{expected}/api/v1"


class TestCoolifyHostnameValidation:
    @pytest.mark.parametrize(
        "url",
        [
            pytest.param("https://127.0.0.1\\@coolify.example.com", id="backslash_authority_smuggling"),
            pytest.param("https://127.0.0.1%5C@coolify.example.com", id="encoded_backslash"),
            pytest.param("https://user@coolify.example.com", id="userinfo"),
            pytest.param("ftp://coolify.example.com", id="non_http_scheme"),
            pytest.param("https://", id="no_host"),
            pytest.param("", id="empty"),
        ],
    )
    def test_rejects_ambiguous_or_malformed_urls(self, url: str) -> None:
        # urlparse and requests disagree on where the authority ends for these shapes, so a URL
        # that validates as one host but connects to another must be rejected outright (SSRF).
        assert hostname_of(url) is None

    def test_accepts_a_plain_instance_url(self) -> None:
        assert hostname_of(BASE_URL) == "coolify.example.com"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.is_cloud",
        return_value=True,
    )
    def test_rejects_plain_http_on_cloud(self, _mock: MagicMock) -> None:
        # On cloud the bearer token would ride in cleartext to a customer-supplied http host.
        assert hostname_of("http://coolify.example.com") is None

    def test_source_refuses_a_rejected_host(self) -> None:
        with pytest.raises(CoolifyHostNotAllowedError):
            coolify_source("https://user@coolify.example.com", "coolify-token", "servers", team_id=1, job_id="job-1")


class TestCoolifyClientConfig:
    @pytest.mark.parametrize(
        "endpoint,capture_disabled",
        [
            pytest.param("applications", True, id="webhook_secrets_in_the_response"),
            pytest.param("databases", True, id="database_credentials_in_the_response"),
            pytest.param("deployments", True, id="deploy_logs_in_the_response"),
            pytest.param("servers", True, id="log_drain_keys_in_the_response"),
            pytest.param("services", True, id="compose_contents_in_the_response"),
            pytest.param("teams", True, id="member_emails_in_the_response"),
            pytest.param("projects", False, id="nothing_to_withhold"),
        ],
    )
    def test_capture_is_disabled_only_where_the_response_must_not_be_sampled(
        self, endpoint: str, capture_disabled: bool
    ) -> None:
        # Sample capture records the raw response before resource maps run, so stripping a field
        # from storage does not keep it out of a sample; those endpoints must turn capture off,
        # and every other endpoint must leave the operator-configured default in place.
        client_config = _client_config(BASE_URL, "coolify-token", COOLIFY_ENDPOINTS[endpoint])
        if capture_disabled:
            assert client_config["capture"] is False
        else:
            assert "capture" not in client_config


class TestCoolifySensitiveFields:
    def test_databases_strip_credentials_of_every_database_type(self) -> None:
        # /databases mixes every standalone database type in one listing, and a token with the
        # `read:sensitive` or `root` ability gets the credential fields back; each type's
        # password and connection URLs must be gone before the record is stored.
        record = {
            "uuid": "db-1",
            "name": "prod-pg",
            "postgres_password": "leak-me",
            "internal_db_url": "postgres://coolify:leak-me@db:5432/prod",
            "external_db_url": "postgres://coolify:leak-me@example.com:5432/prod",
            "init_scripts": [{"filename": "init.sql", "content": "leak-me"}],
        }
        resource = coolify_source(BASE_URL, "coolify-token", "databases", team_id=1, job_id="job-1")

        assert resource._apply_transforms([record]) == [{"uuid": "db-1", "name": "prod-pg"}]

    def test_deployments_strip_logs_and_configuration_snapshots(self) -> None:
        # Deploy logs echo build output (which can print env values) and the configuration
        # snapshot holds the full application config; both are hidden by Coolify for plain read
        # tokens and must not land in the warehouse for privileged ones either.
        record = {
            "deployment_uuid": "dep-1",
            "status": "finished",
            "logs": '[{"output": "leak-me"}]',
            "configuration_snapshot": {"env": "leak-me"},
            "configuration_diff": {"env": "leak-me"},
        }
        resource = coolify_source(BASE_URL, "coolify-token", "deployments", team_id=1, job_id="job-1")

        assert resource._apply_transforms([record]) == [{"deployment_uuid": "dep-1", "status": "finished"}]

    def test_projects_round_trip_untouched(self) -> None:
        # Only endpoints that declare sensitive_fields get filtered; everything else must
        # round-trip untouched or the strip would silently drop real data.
        record = {"uuid": "proj-1", "name": "web", "description": None}
        resource = coolify_source(BASE_URL, "coolify-token", "projects", team_id=1, job_id="job-1")

        assert resource._apply_transforms([dict(record)]) == [record]


class TestCoolifyFlatEndpoints:
    def test_reads_the_bare_array_from_the_versioned_path(self, requests_mock: Any) -> None:
        # Coolify list endpoints answer a bare JSON array under /api/v1; a wrong data_selector or
        # a doubled/missing API prefix would sync zero rows without erroring.
        servers = requests_mock.get(f"{API_BASE}/servers", json=[{"uuid": "srv-1", "name": "hetzner-1"}])

        assert _rows("servers", base_url=f"{BASE_URL}/api/v1") == [{"uuid": "srv-1", "name": "hetzner-1"}]
        assert servers.call_count == 1


class TestCoolifyDeploymentsFanout:
    def _mock_applications(self, requests_mock: Any, uuids: list[str]) -> None:
        requests_mock.get(f"{API_BASE}/applications", json=[{"uuid": uuid, "name": f"app-{uuid}"} for uuid in uuids])

    def test_deployments_carry_their_parent_application_uuid(self, requests_mock: Any) -> None:
        # Deployment rows only carry the numeric application_id; the parent's uuid projection
        # (renamed off the `_applications_` prefix) is what joins them to the applications
        # table's primary key.
        self._mock_applications(requests_mock, [APP_UUID])
        requests_mock.get(
            f"{API_BASE}/deployments/applications/{APP_UUID}",
            json={"count": 1, "deployments": [{"deployment_uuid": "dep-1", "status": "finished"}]},
        )

        assert _rows("deployments") == [
            {"deployment_uuid": "dep-1", "status": "finished", "application_uuid": APP_UUID}
        ]

    def test_pages_with_skip_and_take_until_the_reported_count(self, requests_mock: Any) -> None:
        # The endpoint pages with skip/take and reports the grand total under `count`; wrong
        # param names or a wrong total path would either sync only the newest page or loop.
        self._mock_applications(requests_mock, [APP_UUID])
        page_one = [{"deployment_uuid": f"dep-{i}"} for i in range(DEPLOYMENTS_PAGE_SIZE)]
        page_two = [{"deployment_uuid": "dep-last"}]
        deployments = requests_mock.get(
            f"{API_BASE}/deployments/applications/{APP_UUID}",
            [
                {"json": {"count": DEPLOYMENTS_PAGE_SIZE + 1, "deployments": page_one}},
                {"json": {"count": DEPLOYMENTS_PAGE_SIZE + 1, "deployments": page_two}},
            ],
        )

        rows = _rows("deployments")

        assert len(rows) == DEPLOYMENTS_PAGE_SIZE + 1
        assert deployments.call_count == 2
        first_request, second_request = deployments.request_history
        assert first_request.qs["take"] == [str(DEPLOYMENTS_PAGE_SIZE)]
        assert second_request.qs["skip"] == [str(DEPLOYMENTS_PAGE_SIZE)]

    def test_an_application_deleted_mid_sync_does_not_fail_the_table(self, requests_mock: Any) -> None:
        # An app removed between the parent listing and its child fetch answers 404; one such app
        # must cost only its own rows, not the whole deployments table.
        gone_uuid = "gone0000000000000000000000"
        self._mock_applications(requests_mock, [gone_uuid, APP_UUID])
        requests_mock.get(f"{API_BASE}/deployments/applications/{gone_uuid}", status_code=404, json={})
        requests_mock.get(
            f"{API_BASE}/deployments/applications/{APP_UUID}",
            json={"count": 1, "deployments": [{"deployment_uuid": "dep-1"}]},
        )

        assert [row["deployment_uuid"] for row in _rows("deployments")] == ["dep-1"]


class TestCoolifyValidateCredentials:
    def test_rejects_an_invalid_url_without_a_network_call(self) -> None:
        valid, error = validate_credentials("https://user@coolify.example.com", "coolify-token")
        assert not valid
        assert error is not None
        assert "instance URL" in error

    @pytest.mark.parametrize(
        "status_code,expected_valid,expected_fragment",
        [
            pytest.param(200, True, None, id="ok"),
            # Coolify answers an unrecognized token with 400 "Invalid token." rather than 401.
            pytest.param(400, False, "rejected the API token", id="invalid_token_400"),
            pytest.param(401, False, "rejected the API token", id="unauthenticated"),
            pytest.param(403, False, "read permission", id="missing_read_ability"),
            pytest.param(500, False, "try again", id="transient_server_error"),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.make_tracked_session")
    def test_maps_status_to_a_message(
        self, mock_session: MagicMock, status_code: int, expected_valid: bool, expected_fragment: str | None
    ) -> None:
        mock_session.return_value.get.return_value = _make_response(status_code=status_code)

        valid, error = validate_credentials(BASE_URL, "coolify-token", team_id=1)

        assert valid is expected_valid
        if expected_fragment is not None:
            assert error is not None and expected_fragment in error

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.make_tracked_session")
    def test_transport_error_does_not_blame_the_token(self, mock_session: MagicMock) -> None:
        # An unreachable instance is not proof the token is bad; the message must point at the
        # URL, not tell the user to regenerate a good token.
        mock_session.return_value.get.side_effect = ConnectionError("boom")

        valid, error = validate_credentials(BASE_URL, "coolify-token", team_id=1)

        assert not valid
        assert error is not None and "reach" in error

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify.make_tracked_session")
    def test_probes_the_normalized_teams_endpoint(self, mock_session: MagicMock) -> None:
        # A pasted `/api/v1` suffix must not double into `/api/v1/api/v1/teams`.
        mock_session.return_value.get.return_value = _make_response(json_body=[], status_code=200)

        validate_credentials(f"{BASE_URL}/api/v1/", "coolify-token", team_id=1)

        args, _ = mock_session.return_value.get.call_args
        assert args[0] == f"{API_BASE}/teams"
