import base64
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import parse_qs

import pytest
from unittest import mock

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.sources.workday._config import WorkdaySourceConfig
from products.warehouse_sources.sources.workday.settings import WORKDAY_ENDPOINTS, build_endpoint_path
from products.warehouse_sources.sources.workday.source import WorkdaySource
from products.warehouse_sources.sources.workday.workday import (
    HOST_NOT_ALLOWED_ERROR,
    TOKEN_ERROR,
    WorkdayAuthError,
    WorkdayHostNotAllowedError,
    WorkdayResumeConfig,
    mint_access_token,
    validate_credentials,
)

WORKDAY_MODULE = "products.warehouse_sources.sources.workday.workday"

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
            ("locations", "/staffing/v7/acme_pt1/values/jobChangesGroup/locations/"),
            ("worker_pay_slips", "/v1/acme_pt1/workers/{worker_id}/paySlips"),
            ("worker_history", "/v1/acme_pt1/workers/{worker_id}/history"),
            # Time Tracking has its own version, which the Staffing pin must not move.
            ("worker_time_blocks", "/timeTracking/v7/acme_pt1/workerTimeBlocks"),
        ],
    )
    @pytest.mark.parametrize("staffing_version", ["v7", "v6"])
    def test_build_endpoint_path(self, endpoint: str, expected: str, staffing_version: str) -> None:
        assert build_endpoint_path(WORKDAY_ENDPOINTS[endpoint], "acme_pt1", staffing_version) == expected.replace(
            "/staffing/v7/", f"/staffing/{staffing_version}/"
        )


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

    @pytest.mark.parametrize("schema_name", ["worker_pay_slips", "worker_history"])
    def test_per_worker_schema_probes_the_worker_listing(self, schema_name: str) -> None:
        responses = [_token_response(), _json_response({"total": 1, "data": []})]
        with scripted_network(responses) as network:
            ok, _ = validate_credentials(
                hostname=HOSTNAME,
                tenant=TENANT,
                client_id="client",
                client_secret="secret",
                refresh_token="refresh",
                staffing_version="v7",
                schema_name=schema_name,
            )

        assert ok is True
        assert _data_requests(network.requests_log)[0].path == f"/ccx/api/v1/{TENANT}/workers"

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


def _ids(prefix: str, count: int, start: int = 0) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}{i}"} for i in range(start, start + count)]


WORKERS_PATH = f"/v1/{TENANT}/workers"


class TestPerWorkerTables:
    @pytest.mark.parametrize("endpoint, sub_path", [("worker_pay_slips", "paySlips"), ("worker_history", "history")])
    def test_fans_out_over_every_worker_page_and_child_page(self, endpoint: str, sub_path: str) -> None:
        result = _driver().run(
            endpoint,
            route(
                {
                    "/token": [_token_response()] * 3,
                    WORKERS_PATH: [_page(_ids("w", 100), total=101), _page([{"id": "w100"}], total=101)],
                    f"{WORKERS_PATH}/w0/{sub_path}": [
                        _page(_ids("a", 100), total=101),
                        _page(_ids("a", 1, start=100), total=101),
                    ],
                    **{f"{WORKERS_PATH}/w{n}/{sub_path}": [_page([], total=0)] for n in range(1, 100)},
                    f"{WORKERS_PATH}/w100/{sub_path}": [_page([{"id": "a0"}], total=1)],
                }
            ),
        )

        assert result.raised is None
        keys = [(row["worker_id"], row["id"]) for row in result.rows]
        assert len(keys) == 102
        assert keys[0] == ("w0", "a0") and keys[100] == ("w0", "a100")
        # The same child id under another worker stays a distinct row through the worker in the key.
        assert keys[-1] == ("w100", "a0")
        assert all("_workers_id" not in row for row in result.rows)
        child_requests = [r for r in _data_requests(result.requests) if r.path.endswith(f"/w0/{sub_path}")]
        assert [(r.param("limit"), r.param("offset")) for r in child_requests] == [("100", "0"), ("100", "100")]

    def test_resume_restarts_the_worker_listing_a_page_back_and_skips_finished_workers(self) -> None:
        worker_pages = [
            _page(_ids("w", 100), total=202),
            _page(_ids("w", 100, start=100), total=202),
            _page(_ids("w", 2, start=200), total=202),
        ]
        pay_slips = {f"{WORKERS_PATH}/w{n}/paySlips": [_page([{"id": f"p{n}"}], total=1)] for n in range(202)}
        first = _driver().run(
            "worker_pay_slips",
            route({"/token": [_token_response()] * 3, WORKERS_PATH: list(worker_pages), **pay_slips}),
        )
        assert first.raised is None
        after_w200 = next(
            state
            for state in first.saved_states
            if state.fanout_state and f"{WORKERS_PATH}/w200/paySlips" in state.fanout_state["completed"]
        )

        result = _driver().run(
            "worker_pay_slips",
            route(
                {
                    "/token": [_token_response()] * 3,
                    WORKERS_PATH: worker_pages[1:],
                    f"{WORKERS_PATH}/w201/paySlips": [_page([{"id": "p201"}], total=1)],
                }
            ),
            resume_state=after_w200,
        )

        assert result.raised is None
        worker_requests = [r for r in _data_requests(result.requests) if r.path == f"/ccx/api{WORKERS_PATH}"]
        assert [r.param("offset") for r in worker_requests] == ["100", "200"]
        assert [(row["worker_id"], row["id"]) for row in result.rows] == [("w201", "p201")]


class TestTopLevelTables:
    def test_locations_are_read_in_one_request_without_paging_params(self) -> None:
        result = _driver().run("locations", _tenant_api([_page(_ids("loc", 3), total=3)]))

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["loc0", "loc1", "loc2"]
        (request,) = _data_requests(result.requests)
        assert request.path == f"/ccx/api/staffing/v7/{TENANT}/values/jobChangesGroup/locations/"
        assert request.param("limit") is None and request.param("offset") is None

    def test_time_blocks_page_through_the_time_tracking_service(self) -> None:
        result = _driver().run(
            "worker_time_blocks",
            _tenant_api([_page(_ids("tb", 100), total=101), _page(_ids("tb", 1, start=100), total=101)]),
        )

        assert result.raised is None
        assert len(result.rows) == 101
        requests = _data_requests(result.requests)
        assert {r.path for r in requests} == {f"/ccx/api/timeTracking/v7/{TENANT}/workerTimeBlocks"}
        assert [r.param("offset") for r in requests] == ["0", "100"]
        # Full refresh: no date window, which would filter on the block date, not on changes.
        assert all(r.param("fromDate") is None and r.param("toDate") is None for r in requests)
