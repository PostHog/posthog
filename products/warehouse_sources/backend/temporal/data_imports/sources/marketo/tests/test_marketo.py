import io
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from requests import Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.marketo import (
    BULK_CHUNK_ROWS,
    MarketoAPIError,
    MarketoAuthError,
    MarketoClient,
    MarketoResumeConfig,
    MarketoRetryableError,
    MarketoTokenError,
    _bulk_rows,
    _download_bulk_export,
    _lead_export_fields,
    _normalize_row,
    build_base_url,
    bulk_windows,
    format_datetime,
    get_rows,
    marketo_source,
    parse_datetime,
    raise_for_marketo_errors,
    resolve_bulk_start,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import (
    MARKETO_ENDPOINTS,
    MarketoEndpointConfig,
)

SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.marketo.marketo.make_tracked_session"

MUNCHKIN = "123-ABC-456"


class _RawStream(io.BytesIO):
    """BytesIO that tolerates the ``decode_content`` flag urllib3 raw streams carry."""

    decode_content = False


class FakeResumeManager(ResumableSourceManager[MarketoResumeConfig]):
    def __init__(self, state: Optional[MarketoResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[MarketoResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[MarketoResumeConfig]:
        return self.state

    def save_state(self, data: MarketoResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _response(body: Any, status: int = 200, content_type: str = "application/json") -> Response:
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode() if not isinstance(body, bytes) else body
    response.headers = CaseInsensitiveDict({"Content-Type": content_type})
    return response


def _csv_response(text: str) -> Response:
    response = Response()
    response.status_code = 200
    response.headers = CaseInsensitiveDict({"Content-Type": "text/csv;charset=UTF-8"})
    response.raw = _RawStream(text.encode())
    return response


def _token_body(expires_in: int = 3600, token: str = "tok-1") -> dict[str, Any]:
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "scope": "svc@example.com"}


def _make_client(
    session: mock.MagicMock,
    munchkin_id: str = MUNCHKIN,
) -> MarketoClient:
    with mock.patch(SESSION_PATCH, return_value=session):
        return MarketoClient(munchkin_id, "client-id", "client-secret")


def _session(token_bodies: Optional[list[Any]] = None, responses: Optional[list[Response]] = None) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = [_response(body) for body in (token_bodies or [_token_body()])]
    if responses is not None:
        session.request.side_effect = responses
    return session


def _drain(items: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in cast("Iterable[Any]", items):
        rows.extend(batch)
    return rows


class TestMarketo:
    def test_build_base_url_accepts_a_bare_munchkin_id(self) -> None:
        assert build_base_url(MUNCHKIN) == "https://123-ABC-456.mktorest.com"

    @pytest.mark.parametrize(
        "raw",
        ["  123-ABC-456 ", "https://123-ABC-456.mktorest.com", "123-ABC-456.mktorest.com", "123-ABC-456/"],
    )
    def test_build_base_url_normalizes_pasted_endpoints(self, raw: str) -> None:
        assert build_base_url(raw) == "https://123-ABC-456.mktorest.com"

    @pytest.mark.parametrize("raw", ["", "123 ABC", "evil.com/../x", "123_ABC", "https://evil.com@marketo"])
    def test_build_base_url_rejects_anything_that_is_not_a_munchkin_id(self, raw: str) -> None:
        # The host template is fixed, so a bad id must fail loudly rather than build a weird host.
        with pytest.raises(ValueError):
            build_base_url(raw)

    @pytest.mark.parametrize(
        "value,expected",
        [
            (datetime(2024, 3, 1, 12, 30, tzinfo=UTC), "2024-03-01T12:30:00Z"),
            (datetime(2024, 3, 1, 12, 30), "2024-03-01T12:30:00Z"),
            ("2024-03-01T12:30:00Z", "2024-03-01T12:30:00Z"),
        ],
    )
    def test_format_datetime(self, value: Any, expected: str) -> None:
        assert format_datetime(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("2024-03-01T12:30:00Z", datetime(2024, 3, 1, 12, 30, tzinfo=UTC)),
            ("2024-03-01", datetime(2024, 3, 1, tzinfo=UTC)),
            (datetime(2024, 3, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC)),
            ("not a date", None),
            ("", None),
            (None, None),
        ],
    )
    def test_parse_datetime(self, value: Any, expected: Optional[datetime]) -> None:
        assert parse_datetime(value) == expected

    def test_success_body_raises_nothing(self) -> None:
        raise_for_marketo_errors({"success": True, "result": []})

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("606", MarketoRetryableError),
            ("615", MarketoRetryableError),
            ("1029", MarketoRetryableError),
            ("604", MarketoRetryableError),
            ("601", MarketoTokenError),
            ("602", MarketoTokenError),
            ("603", MarketoAPIError),
            ("607", MarketoAPIError),
            ("1003", MarketoAPIError),
        ],
    )
    def test_error_codes_are_classified_by_whether_retrying_can_help(
        self, code: str, expected: type[Exception]
    ) -> None:
        with pytest.raises(expected) as excinfo:
            raise_for_marketo_errors({"success": False, "errors": [{"code": code, "message": "boom"}]})
        assert f"Marketo API error {code}" in str(excinfo.value)

    def test_retryable_and_token_errors_stay_distinct_from_the_generic_error(self) -> None:
        # 603 must not be treated as retryable — get_non_retryable_errors keys off its message.
        with pytest.raises(MarketoAPIError) as excinfo:
            raise_for_marketo_errors({"success": False, "errors": [{"code": "603", "message": "Access denied"}]})
        assert not isinstance(excinfo.value, MarketoRetryableError | MarketoTokenError)

    def test_token_is_minted_once_and_reused_across_requests(self) -> None:
        session = _session(responses=[_response({"success": True, "result": []})] * 2)
        client = _make_client(session)

        client.request_json("GET", "/rest/v1/campaigns.json")
        client.request_json("GET", "/rest/v1/lists.json")

        assert session.get.call_count == 1
        assert session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-1"

    def test_expired_token_is_reminted_before_the_next_request(self) -> None:
        # expires_in below the safety margin means the cached token is never considered fresh.
        session = _session(
            token_bodies=[_token_body(expires_in=0, token="tok-1"), _token_body(expires_in=0, token="tok-2")],
            responses=[_response({"success": True, "result": []})] * 2,
        )
        client = _make_client(session)

        client.request_json("GET", "/rest/v1/campaigns.json")
        client.request_json("GET", "/rest/v1/lists.json")

        assert session.get.call_count == 2
        assert session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-2"

    def test_http_401_remints_the_token_and_replays_the_request(self) -> None:
        session = _session(
            token_bodies=[_token_body(token="tok-1"), _token_body(token="tok-2")],
            responses=[_response({}, status=401), _response({"success": True, "result": [{"id": 1}]})],
        )
        client = _make_client(session)

        body = client.request_json("GET", "/rest/v1/campaigns.json")

        assert body["result"] == [{"id": 1}]
        assert session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-2"

    def test_persistent_401_surfaces_as_an_auth_error(self) -> None:
        session = _session(
            token_bodies=[_token_body(token="tok-1"), _token_body(token="tok-2")],
            responses=[_response({}, status=401), _response({}, status=401)],
        )
        client = _make_client(session)

        with pytest.raises(MarketoAuthError):
            client.request_json("GET", "/rest/v1/campaigns.json")

    def test_body_level_token_error_remints_and_replays_once(self) -> None:
        session = _session(
            token_bodies=[_token_body(token="tok-1"), _token_body(token="tok-2")],
            responses=[
                _response({"success": False, "errors": [{"code": "602", "message": "Access token expired"}]}),
                _response({"success": True, "result": [{"id": 7}]}),
            ],
        )
        client = _make_client(session)

        assert client.request_json("GET", "/rest/v1/campaigns.json")["result"] == [{"id": 7}]
        assert session.get.call_count == 2

    def test_token_error_that_survives_a_remint_is_raised(self) -> None:
        expired = {"success": False, "errors": [{"code": "601", "message": "Access token invalid"}]}
        session = _session(
            token_bodies=[_token_body(token="tok-1"), _token_body(token="tok-2")],
            responses=[_response(expired), _response(expired)],
        )
        client = _make_client(session)

        with pytest.raises(MarketoTokenError):
            client.request_json("GET", "/rest/v1/campaigns.json")

    def test_identity_endpoint_failure_is_an_auth_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = [_response({"error": "invalid_client"}, status=401)]
        client = _make_client(session)

        with pytest.raises(MarketoAuthError):
            client.access_token()

    def test_transport_error_while_minting_a_token_redacts_credentials(self) -> None:
        # A connection/timeout error carries the prepared URL, which embeds the credentials as
        # query params; that string is persisted as the import's latest_error, so both literals
        # must be scrubbed before the error escapes.
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError(
            "Max retries exceeded with url: /identity/oauth/token?client_id=client-id&client_secret=client-secret"
        )
        client = _make_client(session)

        with pytest.raises(MarketoAuthError) as excinfo:
            client.access_token()

        message = str(excinfo.value)
        assert "client-secret" not in message
        assert "client-id" not in message

    def test_session_is_built_without_http_sample_capture(self) -> None:
        # Marketo responses carry lead emails and arbitrary customer fields the generic scrubber
        # can't recognise, so they must never reach HTTP sample storage.
        with mock.patch(SESSION_PATCH) as session_factory:
            MarketoClient(MUNCHKIN, "client-id", "client-secret")

        assert session_factory.call_args.kwargs["capture"] is False
        assert session_factory.call_args.kwargs["redact_values"] == ("client-id", "client-secret")

    @pytest.mark.parametrize(
        "token_body,status,expected_ok",
        [
            (_token_body(), 200, True),
            ({"error": "invalid_client"}, 401, False),
        ],
    )
    def test_validate_credentials_maps_the_identity_probe(
        self, token_body: dict[str, Any], status: int, expected_ok: bool
    ) -> None:
        session = mock.MagicMock()
        session.get.side_effect = [_response(token_body, status=status)]
        with mock.patch(SESSION_PATCH, return_value=session):
            ok, message = validate_credentials(MUNCHKIN, "client-id", "client-secret")

        assert ok is expected_ok
        assert (message is None) is expected_ok

    def test_validate_credentials_rejects_a_malformed_munchkin_id_without_a_request(self) -> None:
        with mock.patch(SESSION_PATCH) as session_factory:
            ok, message = validate_credentials("not a munchkin", "client-id", "client-secret")

        assert ok is False
        assert message is not None and "Munchkin" in message
        session_factory.assert_not_called()

    def test_token_paging_walks_until_more_result_is_false(self) -> None:
        session = _session(
            responses=[
                _response({"success": True, "result": [{"id": 1}], "nextPageToken": "t2", "moreResult": True}),
                _response({"success": True, "result": [{"id": 2}], "nextPageToken": "t3", "moreResult": False}),
            ]
        )
        manager = FakeResumeManager()

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _drain(get_rows(MUNCHKIN, "cid", "secret", "campaigns", manager, mock.MagicMock()))

        assert rows == [{"id": 1}, {"id": 2}]
        assert [state.next_page_token for state in manager.saved] == ["t2"]
        assert manager.cleared is True

    def test_token_paging_stops_when_the_api_omits_more_result(self) -> None:
        # Activity types return everything in one response with no `moreResult` flag.
        session = _session(responses=[_response({"success": True, "result": [{"id": 1}], "nextPageToken": "t2"})])
        manager = FakeResumeManager()

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _drain(get_rows(MUNCHKIN, "cid", "secret", "activity_types", manager, mock.MagicMock()))

        assert rows == [{"id": 1}]
        assert manager.saved == []

    def test_token_paging_resumes_from_saved_state(self) -> None:
        session = _session(responses=[_response({"success": True, "result": [{"id": 9}], "moreResult": False})])
        manager = FakeResumeManager(MarketoResumeConfig(next_page_token="saved-token"))

        with mock.patch(SESSION_PATCH, return_value=session):
            _drain(get_rows(MUNCHKIN, "cid", "secret", "campaigns", manager, mock.MagicMock()))

        assert session.request.call_args.kwargs["params"]["nextPageToken"] == "saved-token"

    def test_offset_paging_stops_on_the_first_short_page(self) -> None:
        full_page = [{"id": index} for index in range(200)]
        session = _session(
            responses=[
                _response({"success": True, "result": full_page}),
                _response({"success": True, "result": [{"id": 999}]}),
            ]
        )
        manager = FakeResumeManager()

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _drain(get_rows(MUNCHKIN, "cid", "secret", "programs", manager, mock.MagicMock()))

        assert len(rows) == 201
        assert [call.kwargs["params"]["offset"] for call in session.request.call_args_list] == [0, 200]
        assert [state.offset for state in manager.saved] == [200]

    def test_offset_paging_stops_on_an_empty_result(self) -> None:
        session = _session(responses=[_response({"success": True})])
        manager = FakeResumeManager()

        with mock.patch(SESSION_PATCH, return_value=session):
            rows = _drain(get_rows(MUNCHKIN, "cid", "secret", "emails", manager, mock.MagicMock()))

        assert rows == []
        assert session.request.call_count == 1

    def test_offset_paging_resumes_from_saved_state(self) -> None:
        session = _session(responses=[_response({"success": True, "result": [{"id": 1}]})])
        manager = FakeResumeManager(MarketoResumeConfig(offset=400))

        with mock.patch(SESSION_PATCH, return_value=session):
            _drain(get_rows(MUNCHKIN, "cid", "secret", "forms", manager, mock.MagicMock()))

        assert session.request.call_args.kwargs["params"]["offset"] == 400

    @pytest.mark.parametrize(
        "start,end,expected",
        [
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 20, tzinfo=UTC), 1),
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC), 2),
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC), 0),
            (datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC), 0),
        ],
    )
    def test_bulk_windows_respect_marketos_31_day_filter_cap(
        self, start: datetime, end: datetime, expected: int
    ) -> None:
        windows = bulk_windows(start, end)

        assert len(windows) == expected
        assert all((window_end - window_start).days <= 30 for window_start, window_end in windows)
        if windows:
            assert windows[0][0] == start
            assert windows[-1][1] == end

    @pytest.mark.parametrize(
        "resume,incremental,last_value,start_date,expected",
        [
            (
                MarketoResumeConfig(window_start="2024-06-01T00:00:00Z"),
                True,
                "2024-01-01T00:00:00Z",
                "2023-01-01",
                datetime(2024, 6, 1, tzinfo=UTC),
            ),
            (None, True, "2024-01-01T00:00:00Z", "2023-01-01", datetime(2024, 1, 1, tzinfo=UTC)),
            (None, False, "2024-01-01T00:00:00Z", "2023-01-01", datetime(2023, 1, 1, tzinfo=UTC)),
            (None, True, None, "2023-01-01", datetime(2023, 1, 1, tzinfo=UTC)),
        ],
    )
    def test_bulk_start_prefers_resume_then_watermark_then_start_date(
        self,
        resume: Optional[MarketoResumeConfig],
        incremental: bool,
        last_value: Optional[str],
        start_date: Optional[str],
        expected: datetime,
    ) -> None:
        assert resolve_bulk_start(resume, incremental, last_value, start_date) == expected

    def test_bulk_start_falls_back_to_a_lookback_when_nothing_is_configured(self) -> None:
        now = datetime(2024, 6, 1, tzinfo=UTC)

        resolved = resolve_bulk_start(None, False, None, None, now=now)

        assert resolved < now
        assert (now - resolved).days == 365

    def test_bulk_export_runs_create_enqueue_poll_download_per_window(self) -> None:
        csv_text = "marketoGUID,leadId,activityDate,activityTypeId\nabc,7,2024-01-02T00:00:00Z,1\n"
        session = _session(
            responses=[
                _response({"success": True, "result": [{"exportId": "exp-1", "status": "Created"}]}),
                _response({"success": True, "result": [{"exportId": "exp-1", "status": "Queued"}]}),
                _response({"success": True, "result": [{"exportId": "exp-1", "status": "Processing"}]}),
                _response({"success": True, "result": [{"exportId": "exp-1", "status": "Completed"}]}),
                _csv_response(csv_text),
            ]
        )
        manager = FakeResumeManager()
        client = _make_client(session)

        with mock.patch("time.sleep") as sleep:
            rows = _drain(
                _bulk_rows(
                    client,
                    MARKETO_ENDPOINTS["activities"],
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 10, tzinfo=UTC),
                    manager,
                    mock.MagicMock(),
                )
            )

        base = f"https://{MUNCHKIN}.mktorest.com"
        paths = [call.args[1].removeprefix(base) for call in session.request.call_args_list]
        assert paths == [
            "/bulk/v1/activities/export/create.json",
            "/bulk/v1/activities/export/exp-1/enqueue.json",
            "/bulk/v1/activities/export/exp-1/status.json",
            "/bulk/v1/activities/export/exp-1/status.json",
            "/bulk/v1/activities/export/exp-1/file.json",
        ]
        assert rows == [
            {"marketoGUID": "abc", "leadId": 7, "activityDate": "2024-01-02T00:00:00Z", "activityTypeId": 1}
        ]
        # Marketo rejects polling faster than once a minute, so every poll waits first.
        assert sleep.call_count == 2
        assert [state.window_start for state in manager.saved] == ["2024-01-10T00:00:00Z"]

    def test_bulk_export_filters_on_the_window_boundaries(self) -> None:
        session = _session(
            responses=[
                _response({"success": True, "result": [{"exportId": "exp-1"}]}),
                _response({"success": True, "result": [{"exportId": "exp-1"}]}),
                _response({"success": True, "result": [{"status": "Completed"}]}),
                _csv_response("marketoGUID\n"),
            ]
        )
        client = _make_client(session)

        with mock.patch("time.sleep"):
            _drain(
                _bulk_rows(
                    client,
                    MARKETO_ENDPOINTS["activities"],
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 5, tzinfo=UTC),
                    FakeResumeManager(),
                    mock.MagicMock(),
                )
            )

        create_body = session.request.call_args_list[0].kwargs["json"]
        assert create_body["format"] == "CSV"
        assert create_body["filter"]["createdAt"] == {
            "startAt": "2024-01-01T00:00:00Z",
            "endAt": "2024-01-05T00:00:00Z",
        }

    def test_bulk_lead_export_names_every_column_from_describe(self) -> None:
        describe = {
            "success": True,
            "result": [
                {"id": 1, "rest": {"name": "id"}},
                {"id": 2, "rest": {"name": "email"}},
                {"id": 3, "soap": {"name": "OnlySoap"}},
            ],
        }
        session = _session(
            responses=[
                _response(describe),
                _response({"success": True, "result": [{"exportId": "exp-1"}]}),
                _response({"success": True, "result": [{"exportId": "exp-1"}]}),
                _response({"success": True, "result": [{"status": "Completed"}]}),
                _csv_response("id,email\n5,a@example.com\n"),
            ]
        )
        client = _make_client(session)

        with mock.patch("time.sleep"):
            rows = _drain(
                _bulk_rows(
                    client,
                    MARKETO_ENDPOINTS["leads"],
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 5, tzinfo=UTC),
                    FakeResumeManager(),
                    mock.MagicMock(),
                )
            )

        assert session.request.call_args_list[1].kwargs["json"]["fields"] == ["id", "email"]
        assert rows == [{"id": 5, "email": "a@example.com"}]

    def test_lead_export_fields_skip_entries_without_a_rest_name(self) -> None:
        session = _session(
            responses=[_response({"success": True, "result": [{"rest": {"name": "id"}}, {"soap": {"name": "x"}}, {}]})]
        )

        assert _lead_export_fields(_make_client(session)) == ["id"]

    @pytest.mark.parametrize("status", ["Failed", "Cancelled"])
    def test_a_terminal_export_status_fails_the_sync(self, status: str) -> None:
        session = _session(
            responses=[
                _response({"success": True, "result": [{"exportId": "exp-1"}]}),
                _response({"success": True, "result": [{"exportId": "exp-1"}]}),
                _response({"success": True, "result": [{"status": status, "errorMsg": "too much data"}]}),
            ]
        )
        client = _make_client(session)

        with mock.patch("time.sleep"), pytest.raises(MarketoAPIError) as excinfo:
            _drain(
                _bulk_rows(
                    client,
                    MARKETO_ENDPOINTS["activities"],
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 5, tzinfo=UTC),
                    FakeResumeManager(),
                    mock.MagicMock(),
                )
            )

        assert status in str(excinfo.value)
        assert "too much data" in str(excinfo.value)

    def test_a_create_response_without_an_export_id_fails_the_sync(self) -> None:
        session = _session(responses=[_response({"success": True, "result": []})])
        client = _make_client(session)

        with pytest.raises(MarketoAPIError):
            _drain(
                _bulk_rows(
                    client,
                    MARKETO_ENDPOINTS["activities"],
                    datetime(2024, 1, 1, tzinfo=UTC),
                    datetime(2024, 1, 5, tzinfo=UTC),
                    FakeResumeManager(),
                    mock.MagicMock(),
                )
            )

    def test_a_json_error_envelope_on_the_download_is_raised_not_parsed_as_csv(self) -> None:
        client = mock.MagicMock()
        client.request.return_value = _response(
            {"success": False, "errors": [{"code": "1003", "message": "Export not ready"}]}
        )

        with pytest.raises(MarketoAPIError):
            list(_download_bulk_export(client, "leads", "exp-1", ()))

    def test_download_keeps_newlines_inside_quoted_csv_fields(self) -> None:
        client = mock.MagicMock()
        client.request.return_value = _csv_response('id,notes\n1,"line one\nline two"\n')

        rows = _drain(_download_bulk_export(client, "leads", "exp-1", ("id",)))

        assert rows == [{"id": 1, "notes": "line one\nline two"}]

    def test_download_batches_large_exports(self) -> None:
        row_count = BULK_CHUNK_ROWS + 5
        body = "id\n" + "".join(f"{index}\n" for index in range(row_count))
        client = mock.MagicMock()
        client.request.return_value = _csv_response(body)

        batches = list(_download_bulk_export(client, "leads", "exp-1", ("id",)))

        assert [len(batch) for batch in batches] == [BULK_CHUNK_ROWS, 5]

    @pytest.mark.parametrize(
        "row,int_columns,expected",
        [
            ({"id": "42"}, ("id",), {"id": 42}),
            ({"id": ""}, ("id",), {"id": None}),
            ({"id": "not-a-number"}, ("id",), {"id": "not-a-number"}),
            ({"email": "a@b.com"}, ("id",), {"email": "a@b.com"}),
            ({None: ["overflow"]}, (), {}),
        ],
    )
    def test_normalize_row(self, row: dict[Any, Any], int_columns: tuple[str, ...], expected: dict[str, Any]) -> None:
        assert _normalize_row(row, int_columns) == expected

    @pytest.mark.parametrize("endpoint", sorted(MARKETO_ENDPOINTS))
    def test_source_response_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config: MarketoEndpointConfig = MARKETO_ENDPOINTS[endpoint]

        response = marketo_source(MUNCHKIN, "cid", "secret", endpoint, FakeResumeManager(), mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    def test_source_response_items_are_lazy(self) -> None:
        # Building the SourceResponse must not touch the network — the pipeline calls items().
        with mock.patch(SESSION_PATCH) as session_factory:
            marketo_source(MUNCHKIN, "cid", "secret", "campaigns", FakeResumeManager(), mock.MagicMock())

        session_factory.assert_not_called()

    def test_resume_state_is_cleared_only_after_the_endpoint_is_walked(self) -> None:
        session = _session(responses=[_response({"success": True, "result": [{"id": 1}], "moreResult": False})])
        manager = FakeResumeManager()

        with mock.patch(SESSION_PATCH, return_value=session):
            iterator: Iterator[Any] = get_rows(MUNCHKIN, "cid", "secret", "lists", manager, mock.MagicMock())
            next(iterator)
            assert manager.cleared is False
            _drain(iterator)

        assert manager.cleared is True
