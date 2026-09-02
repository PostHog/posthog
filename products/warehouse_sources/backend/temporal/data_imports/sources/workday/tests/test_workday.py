import json
from collections.abc import Iterable
from typing import Any, Optional, cast

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.settings import (
    WORKDAY_ENDPOINTS,
    build_endpoint_path,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workday.workday import (
    HOST_NOT_ALLOWED_ERROR,
    TOKEN_ERROR,
    WorkdayAuthError,
    WorkdayHostNotAllowedError,
    WorkdayResumeConfig,
    base_url,
    mint_access_token,
    normalize_hostname,
    token_url,
    validate_credentials,
    workday_source,
)

WORKDAY_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.workday.workday"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"

HOSTNAME = "wd2-impl-services1.workday.com"
TENANT = "acme_pt1"


class FakeResumeManager(ResumableSourceManager[WorkdayResumeConfig]):
    """Stands in for the Redis-backed manager: no I/O, records what was checkpointed."""

    def __init__(self, state: Optional[WorkdayResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[WorkdayResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[WorkdayResumeConfig]:
        return self.state

    def save_state(self, data: WorkdayResumeConfig) -> None:
        self.saved.append(data)


def _raw_response(content: bytes, *, status_code: int = 200) -> Response:
    response = Response()
    response.status_code = status_code
    response._content = content
    # Callers stream these (stream=True + iter_content) and close them; marking the content
    # consumed makes iter_content replay `_content` and keeps `.close()` a no-op (raw is None).
    response._content_consumed = True  # type: ignore[attr-defined]
    return response


def _json_response(payload: Any, *, status_code: int = 200) -> Response:
    return _raw_response(json.dumps(payload).encode(), status_code=status_code)


def _redirect_response(location: str = "https://internal.example/") -> Response:
    response = _raw_response(b"", status_code=302)
    response.headers["Location"] = location
    return response


def _page(rows: list[dict[str, Any]], total: int) -> Response:
    return _json_response({"total": total, "data": rows})


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request's url + params AT PREPARE TIME.

    ``request.params`` is one dict mutated in place across pages, so it has to be copied when
    each request is prepared rather than read back after the run.
    """
    session.headers = {}
    snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        prepared = mock.MagicMock()
        # `_check_allowed_host` urlsplits the prepared URL, so it must be a real string.
        prepared.url = request.url
        snapshots.append({"url": request.url, "params": dict(request.params or {})})
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return snapshots


def _rows(source_response: SourceResponse) -> list[dict[str, Any]]:
    pages = cast("Iterable[Any]", source_response.items())
    return [row for page in pages for row in page]


def _build_source(
    endpoint: str = "workers",
    manager: Optional[FakeResumeManager] = None,
    staffing_version: str = "v7",
) -> SourceResponse:
    return workday_source(
        hostname=HOSTNAME,
        tenant=TENANT,
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
        endpoint=endpoint,
        staffing_version=staffing_version,
        team_id=1,
        job_id="job-1",
        resumable_source_manager=manager or FakeResumeManager(),
    )


class TestUrlHelpers:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            (HOSTNAME, HOSTNAME),
            (f"https://{HOSTNAME}", HOSTNAME),
            (f"http://{HOSTNAME}/", HOSTNAME),
            (f"  {HOSTNAME}  ", HOSTNAME),
            (f"{HOSTNAME}/acme_pt1", HOSTNAME),
            (f"https://{HOSTNAME}/ccx/api/v1/acme_pt1/workers", HOSTNAME),
        ],
    )
    def test_normalize_hostname(self, raw: str, expected: str) -> None:
        assert normalize_hostname(raw) == expected

    def test_base_url(self) -> None:
        assert base_url(f"https://{HOSTNAME}/") == f"https://{HOSTNAME}/ccx/api"

    def test_token_url(self) -> None:
        assert token_url(HOSTNAME, TENANT) == f"https://{HOSTNAME}/ccx/oauth2/{TENANT}/token"

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

    def test_staffing_paths_follow_the_pinned_version(self) -> None:
        assert build_endpoint_path(WORKDAY_ENDPOINTS["jobs"], TENANT, "v6") == f"/staffing/v6/{TENANT}/jobs"


class TestMintAccessToken:
    def test_posts_refresh_grant_with_basic_client_auth(self) -> None:
        session = mock.MagicMock()
        session.post.return_value = _json_response({"access_token": "tok", "expires_in": 3600})

        with mock.patch(f"{WORKDAY_MODULE}.make_tracked_session", return_value=session):
            assert mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh") == "tok"

        args, kwargs = session.post.call_args
        assert args[0] == f"https://{HOSTNAME}/ccx/oauth2/{TENANT}/token"
        assert kwargs["data"] == {"grant_type": "refresh_token", "refresh_token": "refresh"}
        assert kwargs["auth"] == ("client", "secret")
        # A 3xx must not bounce the client secret to another origin.
        assert kwargs["allow_redirects"] is False

    @pytest.mark.parametrize(
        "response, expected_fragment",
        [
            (_json_response({"error": "invalid_grant"}, status_code=400), TOKEN_ERROR),
            (_json_response({"error": "invalid_client"}, status_code=401), TOKEN_ERROR),
            (_raw_response(b"<html>login</html>"), "non-JSON"),
            (_json_response({"token_type": "Bearer"}), "no access token"),
            (_json_response({"access_token": ""}), "no access token"),
        ],
    )
    def test_token_failures_raise(self, response: Response, expected_fragment: str) -> None:
        session = mock.MagicMock()
        session.post.return_value = response

        with mock.patch(f"{WORKDAY_MODULE}.make_tracked_session", return_value=session):
            with pytest.raises(WorkdayAuthError) as excinfo:
                mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh")

        assert expected_fragment in str(excinfo.value)

    def test_oversized_token_body_is_refused(self) -> None:
        # A customer-controlled host could stream an unbounded token body to exhaust the worker;
        # the read is capped rather than buffered whole.
        session = mock.MagicMock()
        session.post.return_value = _json_response({"access_token": "tok"})

        with (
            mock.patch(f"{WORKDAY_MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{WORKDAY_MODULE}.MAX_VALIDATE_RESPONSE_BYTES", 4),
        ):
            with pytest.raises(WorkdayAuthError) as excinfo:
                mint_access_token(HOSTNAME, TENANT, "client", "secret", "refresh")

        assert "oversized" in str(excinfo.value)


class TestValidateCredentials:
    def _validate(
        self,
        probe: Optional[Response] = None,
        *,
        hostname: str = HOSTNAME,
        tenant: str = TENANT,
        schema_name: Optional[str] = None,
        token_side_effect: Optional[Exception] = None,
    ) -> tuple[bool, Optional[str]]:
        session = mock.MagicMock()
        # `Response.__bool__` is `ok`, so a non-2xx probe must not be treated as absent.
        session.get.return_value = _json_response({"total": 1, "data": []}) if probe is None else probe
        with (
            mock.patch(f"{WORKDAY_MODULE}.make_tracked_session", return_value=session),
            mock.patch(
                f"{WORKDAY_MODULE}.mint_access_token",
                side_effect=token_side_effect,
                return_value="tok",
            ),
        ):
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
        session = mock.MagicMock()
        with mock.patch(f"{WORKDAY_MODULE}.make_tracked_session", return_value=session):
            ok, error = validate_credentials(
                hostname=hostname,
                tenant=tenant,
                client_id="client",
                client_secret="secret",
                refresh_token="refresh",
                staffing_version="v7",
            )

        assert (ok, error) == (False, expected_error)
        session.post.assert_not_called()
        session.get.assert_not_called()

    def test_success(self) -> None:
        assert self._validate() == (True, None)

    def test_probes_the_named_schema_endpoint(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = _json_response({"total": 0, "data": []})
        with (
            mock.patch(f"{WORKDAY_MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{WORKDAY_MODULE}.mint_access_token", return_value="tok"),
        ):
            validate_credentials(
                hostname=HOSTNAME,
                tenant=TENANT,
                client_id="client",
                client_secret="secret",
                refresh_token="refresh",
                staffing_version="v7",
                schema_name="job_profiles",
            )

        args, kwargs = session.get.call_args
        assert args[0] == f"https://{HOSTNAME}/ccx/api/staffing/v7/{TENANT}/jobProfiles"
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["allow_redirects"] is False

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
        ok, error = self._validate(token_side_effect=WorkdayAuthError(f"{TOKEN_ERROR} (HTTP 401)"))
        assert ok is False
        assert error is not None and TOKEN_ERROR in error

    def test_network_failure_is_surfaced(self) -> None:
        ok, error = self._validate(token_side_effect=RequestsConnectionError("dns failure"))
        assert (ok, error) == (False, "dns failure")


class TestWorkdaySource:
    def test_paginates_until_the_total_is_reached(self) -> None:
        session = mock.MagicMock()
        first = [{"id": str(index)} for index in range(100)]
        second = [{"id": "100"}]
        snapshots = _wire(session, [_page(first, total=101), _page(second, total=101)])

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            rows = _rows(_build_source())

        assert [row["id"] for row in rows] == [str(index) for index in range(101)]
        assert [snapshot["params"]["offset"] for snapshot in snapshots] == [0, 100]
        assert snapshots[0]["params"]["limit"] == 100
        assert snapshots[0]["url"] == f"https://{HOSTNAME}/ccx/api/v1/{TENANT}/workers"

    def test_stops_on_an_empty_page_when_the_total_overstates(self) -> None:
        session = mock.MagicMock()
        # `total` overstates what the tenant actually hands back, so termination has to fall back
        # to the empty page rather than looping on the same offset until the total is "reached".
        full_page = [{"id": str(index)} for index in range(100)]
        _wire(session, [_page(full_page, total=5000), _page([], total=5000)])

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            rows = _rows(_build_source())

        assert len(rows) == 100
        assert session.send.call_count == 2

    def test_stops_on_a_short_page(self) -> None:
        session = mock.MagicMock()
        _wire(session, [_page([{"id": "1"}], total=5000)])

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            rows = _rows(_build_source())

        assert [row["id"] for row in rows] == ["1"]
        assert session.send.call_count == 1

    def test_checkpoints_after_each_page(self) -> None:
        session = mock.MagicMock()
        _wire(session, [_page([{"id": str(i)} for i in range(100)], total=101), _page([{"id": "100"}], total=101)])
        manager = FakeResumeManager()

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            _rows(_build_source(manager=manager))

        # One checkpoint after the first page (pointing at the next offset); none once the walk
        # finished, so a later attempt restarts cleanly instead of resuming past the end.
        assert [state.offset for state in manager.saved] == [100]

    def test_resumes_from_the_saved_offset(self) -> None:
        session = mock.MagicMock()
        snapshots = _wire(session, [_page([{"id": "200"}], total=201)])
        manager = FakeResumeManager(WorkdayResumeConfig(offset=200))

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            rows = _rows(_build_source(manager=manager))

        assert snapshots[0]["params"]["offset"] == 200
        assert [row["id"] for row in rows] == ["200"]

    def test_ignores_a_zero_resume_offset(self) -> None:
        session = mock.MagicMock()
        snapshots = _wire(session, [_page([{"id": "0"}], total=1)])

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            _rows(_build_source(manager=FakeResumeManager(WorkdayResumeConfig(offset=0))))

        assert snapshots[0]["params"]["offset"] == 0

    @pytest.mark.parametrize("endpoint", sorted(WORKDAY_ENDPOINTS))
    def test_every_endpoint_requests_its_documented_path(self, endpoint: str) -> None:
        session = mock.MagicMock()
        snapshots = _wire(session, [_page([], total=0)])

        with mock.patch(CLIENT_SESSION_PATCH, return_value=session):
            response = _build_source(endpoint=endpoint)
            _rows(response)

        expected_path = build_endpoint_path(WORKDAY_ENDPOINTS[endpoint], TENANT, "v7")
        assert snapshots[0]["url"] == f"https://{HOSTNAME}/ccx/api{expected_path}"
        assert response.name == endpoint
        assert response.primary_keys == ["id"]

    def test_full_refresh_declares_no_sort_order(self) -> None:
        # Workday's REST collections have no ordering guarantee and no server-side time filter,
        # so claiming "asc" would be a lie the incremental checkpointing could act on.
        assert _build_source().sort_mode is None

    def test_internal_hostname_is_blocked_at_run_time(self) -> None:
        session = mock.MagicMock()
        _wire(session, [_page([], total=0)])

        with (
            mock.patch(CLIENT_SESSION_PATCH, return_value=session),
            mock.patch(f"{WORKDAY_MODULE}._is_host_safe", return_value=(False, None)),
        ):
            with pytest.raises(WorkdayHostNotAllowedError):
                _rows(_build_source())

        session.send.assert_not_called()
