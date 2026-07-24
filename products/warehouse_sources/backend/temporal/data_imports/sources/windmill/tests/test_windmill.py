import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.settings import (
    ENDPOINTS,
    WINDMILL_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill import (
    PER_PAGE,
    WindmillHostNotAllowedError,
    WindmillResumeConfig,
    _format_after,
    _workspace_url,
    normalize_base_url,
    validate_credentials,
    windmill_source,
)

BASE_URL = "https://app.windmill.dev"
WORKSPACE = "my-workspace"

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the windmill module.
WINDMILL_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill.make_tracked_session"
)
HOST_SAFE_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.windmill.windmill._is_host_safe"


def _make_manager(resume_state: WindmillResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _probe_response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 400
    return resp


def _json_response(body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    return resp


def _page(n: int) -> list[dict[str, Any]]:
    return [{"id": str(i)} for i in range(n)]


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Wire a mock session; return (param snapshots, send-kwargs snapshots) captured AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so snapshot a copy when each
    request is prepared rather than inspecting it after the run.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    send_kwargs: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        return mock.MagicMock()

    def _send(prepared: Any, **kwargs: Any) -> Response:
        send_kwargs.append(kwargs)
        return _send.responses.pop(0)  # type: ignore[attr-defined]

    _send.responses = list(responses)  # type: ignore[attr-defined]
    session.prepare_request.side_effect = _prepare
    session.send.side_effect = _send
    return param_snapshots, send_kwargs


def _run(endpoint: str, **kwargs: Any) -> Any:
    manager = kwargs.pop("manager", None) or _make_manager()
    return windmill_source(
        "token", BASE_URL, WORKSPACE, endpoint, team_id=1, job_id="j", resumable_source_manager=manager, **kwargs
    )


def _rows(source_response: Any) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://app.windmill.dev", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev/", "https://app.windmill.dev/api"),
            # A user pasting the full API root must not produce /api/api.
            ("https://app.windmill.dev/api", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev/api/", "https://app.windmill.dev/api"),
            # Plaintext is upgraded to https; a scheme-less host gets one.
            ("http://windmill.internal.example.com", "https://windmill.internal.example.com/api"),
            ("windmill.example.com", "https://windmill.example.com/api"),
            ("  https://app.windmill.dev  ", "https://app.windmill.dev/api"),
            # Embedded userinfo / query / fragment must not change the authority we connect to,
            # so the SSRF host check can't diverge from the effective request host.
            ("https://user:pw@app.windmill.dev", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev?x=1", "https://app.windmill.dev/api"),
            ("https://app.windmill.dev#frag", "https://app.windmill.dev/api"),
            # A custom port is preserved for self-hosted instances.
            ("https://windmill.internal:8080", "https://windmill.internal:8080/api"),
        ],
    )
    def test_normalizes(self, value, expected):
        assert normalize_base_url(value) == expected


class TestWorkspaceUrl:
    def test_builds_workspace_scoped_path(self):
        assert (
            _workspace_url(BASE_URL, WORKSPACE, "/jobs/completed/list")
            == "https://app.windmill.dev/api/w/my-workspace/jobs/completed/list"
        )

    def test_url_encodes_workspace(self):
        # A workspace id with a slash must not escape the /w/ path segment.
        assert "/w/a%2Fb/" in _workspace_url(BASE_URL, "a/b", "/users/list")


class TestFormatAfter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            (date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("already-a-string", "already-a-string"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_after(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid Windmill API token"),
            (403, False, "Could not access Windmill workspace 'my-workspace' with this token"),
            (404, False, "Could not access Windmill workspace 'my-workspace' with this token"),
        ],
    )
    @mock.patch(WINDMILL_SESSION_PATCH)
    def test_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        mock_session.return_value.get.return_value = _probe_response({"message": "x"}, status_code=status_code)

        valid, message = validate_credentials("token", BASE_URL, WORKSPACE)

        assert valid is expected_valid
        assert message == expected_message

    @mock.patch(WINDMILL_SESSION_PATCH)
    def test_uses_no_redirect_session(self, mock_session):
        mock_session.return_value.get.return_value = _probe_response({}, status_code=200)
        validate_credentials("token", BASE_URL, WORKSPACE)
        assert mock_session.call_args.kwargs["allow_redirects"] is False

    @mock.patch(WINDMILL_SESSION_PATCH)
    def test_redacts_api_token_in_tracked_session(self, mock_session):
        # The bearer token rides in a header the name-based scrubbers can't see, so it must be
        # value-redacted or it leaks into captured request samples.
        mock_session.return_value.get.return_value = _probe_response({}, status_code=200)
        validate_credentials("token", BASE_URL, WORKSPACE)
        assert mock_session.call_args.kwargs["redact_values"] == ("token",)

    @mock.patch(WINDMILL_SESSION_PATCH)
    def test_swallows_request_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        valid, message = validate_credentials("token", BASE_URL, WORKSPACE)
        assert valid is False
        assert message == "boom"

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(WINDMILL_SESSION_PATCH)
    def test_blocks_internal_host_when_team_id_given(self, mock_session, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")

        valid, message = validate_credentials("token", "https://10.0.0.1", WORKSPACE, team_id=42)

        assert valid is False
        assert message == "host not allowed"
        mock_session.return_value.get.assert_not_called()

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(WINDMILL_SESSION_PATCH)
    def test_skips_host_check_when_team_id_omitted(self, mock_session, mock_host_safe):
        mock_session.return_value.get.return_value = _probe_response({}, status_code=200)
        validate_credentials("token", BASE_URL, WORKSPACE)
        mock_host_safe.assert_not_called()


class TestSync:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_pages_until_short_page(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(PER_PAGE)), _json_response(_page(3))])

        rows = _rows(_run("completed_jobs"))

        # A short (< per_page) page ends the scan without paying an extra empty-page request.
        assert len(rows) == PER_PAGE + 3
        assert session.send.call_count == 2
        assert params[0]["page"] == 1
        assert params[0]["per_page"] == PER_PAGE
        assert params[1]["page"] == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_stops_on_empty_full_page_boundary(self, MockSession):
        # A full final page is followed by one more request that comes back empty.
        session = MockSession.return_value
        _wire(session, [_json_response(_page(PER_PAGE)), _json_response([])])

        rows = _rows(_run("completed_jobs"))

        assert len(rows) == PER_PAGE
        assert session.send.call_count == 2

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession):
        session = MockSession.return_value
        _wire(session, [_json_response([])])

        manager = _make_manager()
        rows = _rows(_run("completed_jobs", manager=manager))

        assert rows == []
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unpaginated_endpoint_makes_single_request(self, MockSession):
        # listUsers ignores page params, so paging would loop forever on the same full list.
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response([{"email": "a@x.com"}, {"email": "b@x.com"}])])

        manager = _make_manager()
        rows = _rows(_run("users", manager=manager))

        assert session.send.call_count == 1
        assert [item["email"] for item in rows] == ["a@x.com", "b@x.com"]
        assert "page" not in params[0]
        assert "per_page" not in params[0]
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_saves_next_page_after_each_committed_page(self, MockSession):
        # The resume hook fires after a page is yielded and persists the NEXT page to fetch, so a
        # crash re-scans from a page whose predecessors are all committed (merge dedupes overlap).
        session = MockSession.return_value
        _wire(session, [_json_response(_page(PER_PAGE)), _json_response(_page(PER_PAGE)), _json_response(_page(1))])

        manager = _make_manager()
        _rows(_run("completed_jobs", manager=manager))

        saved = [call.args[0].page for call in manager.save_state.call_args_list]
        # Full pages 1 and 2 each checkpoint the following page; the short final page 3 checkpoints
        # nothing (no next page remains).
        assert saved == [2, 3]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_page(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(2))])

        manager = _make_manager(WindmillResumeConfig(page=7))
        _rows(_run("completed_jobs", manager=manager))

        assert params[0]["page"] == 7

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_resume_ignores_saved_page(self, MockSession):
        # The watermark may have advanced since page 7 was saved, so honouring the saved page would
        # skip earlier unsynced rows in the re-filtered result set. Restart from page 1.
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(1))])

        manager = _make_manager(WindmillResumeConfig(page=7))
        _rows(
            _run(
                "completed_jobs",
                manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="started_at",
            )
        )

        assert params[0]["page"] == 1

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_applies_after_filter(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(1))])

        _rows(
            _run(
                "completed_jobs",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="started_at",
            )
        )

        assert params[0]["started_after"].startswith("2026-01-01")

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [("created_at", "created_after"), ("started_at", "started_after")],
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_field_maps_to_after_param(self, MockSession, incremental_field, expected_param):
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(1))])

        _rows(
            _run(
                "completed_jobs",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )

        assert params[0][expected_param] == "2026-01-01T00:00:00+00:00"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_endpoint_never_sends_after_filter(self, MockSession):
        # scripts has no server-side timestamp filter, so a cutoff must never leak into params.
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(1))])

        _rows(
            _run(
                "scripts",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
                incremental_field="created_at",
            )
        )

        assert "created_after" not in params[0]
        assert "started_after" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_order_desc_ascending_for_sortable_endpoint(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(1))])

        _rows(_run("completed_jobs"))
        # Ascending so mid-sync inserts don't shift already-walked pages.
        assert params[0]["order_desc"] == "false"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_no_order_desc_for_unsortable_endpoint(self, MockSession):
        session = MockSession.return_value
        params, _ = _wire(session, [_json_response(_page(1))])

        _rows(_run("schedules"))
        assert "order_desc" not in params[0]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_bearer_token_redacted_via_client_session(self, MockSession):
        # The bearer token is supplied through framework auth, whose secret values feed the tracked
        # session's value redaction so the token can't leak into captured samples or error text.
        session = MockSession.return_value
        _wire(session, [_json_response(_page(1))])

        _rows(_run("completed_jobs"))
        assert MockSession.call_args.kwargs["redact_values"] == ("token",)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_does_not_follow_redirects(self, MockSession):
        session = MockSession.return_value
        _, send_kwargs = _wire(session, [_json_response(_page(1))])

        _rows(_run("completed_jobs"))
        assert send_kwargs[0]["allow_redirects"] is False

    @mock.patch(HOST_SAFE_PATCH)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_raises_when_host_not_allowed(self, MockSession, mock_host_safe):
        mock_host_safe.return_value = (False, "host not allowed")
        session = MockSession.return_value
        _wire(session, [_json_response(_page(1))])

        with pytest.raises(WindmillHostNotAllowedError):
            _rows(_run("completed_jobs"))

        session.send.assert_not_called()


class TestWindmillSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = WINDMILL_ENDPOINTS[endpoint]
        response = windmill_source(
            "token", BASE_URL, WORKSPACE, endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(WINDMILL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        # Partition keys must be immutable creation timestamps, never edited/last-* fields.
        if config.partition_key:
            assert config.partition_key in {"created_at", "timestamp"}
