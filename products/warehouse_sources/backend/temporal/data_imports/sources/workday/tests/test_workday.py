import base64
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import parse_qs

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workday import (
    WorkdaySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.settings import (
    WORKDAY_ENDPOINTS,
    build_endpoint_path,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.source import WorkdaySource
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.workday import (
    HOST_NOT_ALLOWED_ERROR,
    TOKEN_ERROR,
    WorkdayAuthError,
    WorkdayHostNotAllowedError,
    WorkdayResumeConfig,
    mint_access_token,
    validate_credentials,
)

WORKDAY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.workday.workday"

HOSTNAME = "wd2-impl-services1.workday.com"
TENANT = "acme_pt1"

TOKEN_PATH = f"/ccx/oauth2/{TENANT}/token"


def _json_response(payload: Any, *, status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=payload)


def _redirect_response(location: str = "https://internal.example/") -> ScriptedResponse:
    return ScriptedResponse(status=302, headers={"Location": location}, body=b"")


def _page(rows: list[dict[str, Any]], total: int) -> ScriptedResponse:
    return _json_response({"total": total, "data": rows})


def _token_response() -> ScriptedResponse:
    return _json_response({"access_token": "tok", "expires_in": 3600})


def _tenant_api(
    pages: list[ScriptedResponse], token: Optional[ScriptedResponse] = None
) -> Callable[[RecordedRequest], ScriptedResponse]:
    """Answer the token exchange from `token`, and every other request from `pages` in order."""
    queue = list(pages)

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/token"):
            return token or _token_response()
        return queue.pop(0)

    return respond


def _driver() -> SourceDriver:
    config = WorkdaySourceConfig(
        hostname=HOSTNAME, tenant=TENANT, client_id="client", client_secret="secret", refresh_token="refresh"
    )
    return SourceDriver(WorkdaySource(), config)


def _data_requests(requests_log: list[RecordedRequest]) -> list[RecordedRequest]:
    return [request for request in requests_log if not request.path.endswith("/token")]


class TestUrlHelpers:
    @pytest.mark.parametrize(
        "endpoint, expected",
        [
            # The Common service is served straight off /ccx/api/v1 with no service segment.
            ("workers", "/v1/acme_pt1/workers"),
            ("jobs", "/staffing/v7/acme_pt1/jobs"),
            ("job_profiles", "/staffing/v7/acme_pt1/jobProfiles"),
            ("job_families", "/staffing/v7/acme_pt1/jobFamilies"),
            ("supervisory_organizations", "/staffing/v7/acme_pt1/supervisoryOrganizations"),
            ("job_changes", "/staffing/v7/acme_pt1/jobChanges"),
            ("organization_assignment_changes", "/staffing/v7/acme_pt1/organizationAssignmentChanges"),
        ],
    )
    def test_build_endpoint_path(self, endpoint: str, expected: str) -> None:
        assert build_endpoint_path(WORKDAY_ENDPOINTS[endpoint], "acme_pt1", "v7") == expected


class TestMintAccessToken:
    def test_posts_refresh_grant_with_basic_client_auth(self) -> None:
        with scripted_network([_token_response()]) as network:
            assert mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh") == "tok"

        request = network.requests_log[0]
        assert request.url == f"https://{HOSTNAME}{TOKEN_PATH}"
        assert request.body is not None
        assert parse_qs(request.body.decode()) == {"grant_type": ["refresh_token"], "refresh_token": ["refresh"]}
        assert request.headers["authorization"] == f"Basic {base64.b64encode(b'client:secret').decode()}"

    def test_redirect_cannot_bounce_the_client_secret_to_another_origin(self) -> None:
        with scripted_network([_redirect_response()]) as network:
            with pytest.raises(WorkdayAuthError, match="HTTP 302"):
                mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh")

        assert len(network.requests_log) == 1

    @pytest.mark.parametrize(
        "response, expected_fragment",
        [
            (_json_response({"error": "invalid_grant"}, status_code=400), TOKEN_ERROR),
            (_json_response({"error": "invalid_client"}, status_code=401), TOKEN_ERROR),
            (ScriptedResponse(body=b"<html>login</html>"), "non-JSON"),
            (_json_response({"token_type": "Bearer"}), "no access token"),
            (_json_response({"access_token": ""}), "no access token"),
        ],
    )
    def test_token_failures_raise(self, response: ScriptedResponse, expected_fragment: str) -> None:
        with scripted_network([response]):
            with pytest.raises(WorkdayAuthError) as excinfo:
                mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh")

        assert expected_fragment in str(excinfo.value)

    def test_oversized_token_body_is_refused(self) -> None:
        # A customer-controlled host could stream an unbounded token body to exhaust the worker;
        # the read is capped rather than buffered whole.
        with (
            scripted_network([_json_response({"access_token": "tok"})]),
            mock.patch(f"{WORKDAY_MODULE}.MAX_VALIDATE_RESPONSE_BYTES", 4),
        ):
            with pytest.raises(WorkdayAuthError) as excinfo:
                mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh")

        assert "oversized" in str(excinfo.value)


class TestValidateCredentials:
    def _validate(
        self,
        probe: Optional[ScriptedResponse] = None,
        *,
        hostname: str = HOSTNAME,
        tenant: str = TENANT,
        schema_name: Optional[str] = None,
        token: Optional[ScriptedResponse] = None,
    ) -> tuple[bool, Optional[str]]:
        answer = _json_response({"total": 1, "data": []}) if probe is None else probe

        # The stack retries a 5xx, so the probe answers every attempt.
        def responder(request: RecordedRequest) -> ScriptedResponse:
            if request.path.endswith("/token"):
                return token or _token_response()
            return answer

        with scripted_network(responder):
            return validate_credentials(
                hostname=hostname,
                tenant=tenant,
                client_id="client",
                client_secret="secret",
                refresh_token="refresh",
                staffing_version="v7",
                schema_name=schema_name,
            )

    @pytest.mark.parametrize(
        "hostname, tenant, expected_error",
        [
            ("not a host", TENANT, "Invalid Workday hostname"),
            ("", TENANT, "Invalid Workday hostname"),
            (HOSTNAME, "bad tenant", "Invalid Workday tenant"),
            (HOSTNAME, "", "Invalid Workday tenant"),
        ],
    )
    def test_rejects_malformed_target_before_sending_credentials(
        self, hostname: str, tenant: str, expected_error: str
    ) -> None:
        with scripted_network([]) as network:
            ok, error = validate_credentials(
                hostname=hostname,
                tenant=tenant,
                client_id="client",
                client_secret="secret",
                refresh_token="refresh",
                staffing_version="v7",
            )

        assert (ok, error) == (False, expected_error)
        assert network.requests_log == []

    @pytest.mark.parametrize(
        "status_code, schema_name, expected_ok",
        [
            (200, None, True),
            (401, None, False),
            # A genuine client may simply lack the domain security policy for the create-time
            # probe, so 403 must not block source creation — but it fails a scoped probe.
            (403, None, True),
            (403, "workers", False),
            (404, None, False),
            (500, None, False),
        ],
    )
    def test_status_mapping(self, status_code: int, schema_name: Optional[str], expected_ok: bool) -> None:
        ok, _ = self._validate(_json_response({}, status_code=status_code), schema_name=schema_name)
        assert ok is expected_ok

    def test_redirect_is_rejected(self) -> None:
        ok, error = self._validate(_redirect_response())
        assert ok is False
        assert error == HOST_NOT_ALLOWED_ERROR

    def test_token_failure_is_surfaced(self) -> None:
        ok, error = self._validate(token=_json_response({"error": "invalid_client"}, status_code=401))
        assert ok is False
        assert error is not None and TOKEN_ERROR in error


class TestWorkdaySource:
    def test_checkpoints_after_each_page(self) -> None:
        result = _driver().run(
            "workers",
            _tenant_api([_page([{"id": str(i)} for i in range(100)], total=101), _page([{"id": "100"}], total=101)]),
        )

        # One checkpoint after the first page (pointing at the next offset); none once the walk
        # finished, so a later attempt restarts cleanly instead of resuming past the end.
        assert [state.offset for state in result.saved_states] == [100]

    def test_resumes_from_the_saved_offset(self) -> None:
        result = _driver().run(
            "workers",
            _tenant_api([_page([{"id": "200"}], total=201)]),
            resume_state=WorkdayResumeConfig(offset=200),
        )

        assert _data_requests(result.requests)[0].param("offset") == "200"
        assert [row["id"] for row in result.rows] == ["200"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("workers", _tenant_api([_page([{"id": "1"}], total=1)]))

        assert _data_requests(result.requests)[0].param("offset") == "0"

    def test_internal_hostname_is_blocked_at_run_time(self) -> None:
        with mock.patch(f"{WORKDAY_MODULE}._is_host_safe", return_value=(False, None)):
            result = _driver().run("workers", _tenant_api([_page([], total=0)]))

        assert isinstance(result.raised, WorkdayHostNotAllowedError)
        assert result.requests == []
