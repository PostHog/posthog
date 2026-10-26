import io
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
from requests import Response
from requests.structures import CaseInsensitiveDict

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.marketo import (
    MarketoSourceConfig,
)
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
    _normalize_row,
    build_base_url,
    format_datetime,
    marketo_source,
    parse_datetime,
    raise_for_marketo_errors,
    resolve_bulk_start,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.settings import MARKETO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.marketo.source import MarketoSource

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


def _driver(start_date: str = "2024-01-01") -> SourceDriver:
    return SourceDriver(
        MarketoSource(),
        MarketoSourceConfig(
            munchkin_id=MUNCHKIN,
            client_id="client-id",
            client_secret="client-secret",
            start_date=start_date,
        ),
    )


def _token_response(token: str = "tok-1") -> ScriptedResponse:
    return ScriptedResponse(json=_token_body(token=token))


def _ok(body: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"success": True, **body})


def _recent_start() -> str:
    return format_datetime(datetime.now(UTC) - timedelta(days=5))


class TestMarketo:
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

    def test_persistent_401_surfaces_as_an_auth_error(self) -> None:
        with scripted_network(
            [
                _token_response("tok-1"),
                ScriptedResponse(status=401, json={}),
                _token_response("tok-2"),
                ScriptedResponse(status=401, json={}),
            ]
        ) as network:
            client = MarketoClient(MUNCHKIN, "client-id", "client-secret")
            with pytest.raises(MarketoAuthError):
                client.request_json("GET", "/rest/v1/campaigns.json")

        assert [request.path for request in network.requests_log] == [
            "/identity/oauth/token",
            "/rest/v1/campaigns.json",
            "/identity/oauth/token",
            "/rest/v1/campaigns.json",
        ]
        assert [request.headers.get("authorization") for request in network.requests_log[1::2]] == [
            "Bearer tok-1",
            "Bearer tok-2",
        ]

    def test_body_level_token_error_remints_and_replays_once(self) -> None:
        with scripted_network(
            [
                _token_response("tok-1"),
                ScriptedResponse(
                    json={"success": False, "errors": [{"code": "602", "message": "Access token expired"}]}
                ),
                _token_response("tok-2"),
                ScriptedResponse(json={"success": True, "result": [{"id": 7}]}),
            ]
        ) as network:
            client = MarketoClient(MUNCHKIN, "client-id", "client-secret")
            assert client.request_json("GET", "/rest/v1/campaigns.json")["result"] == [{"id": 7}]

        assert [request.path for request in network.requests_log].count("/identity/oauth/token") == 2

    def test_token_error_that_survives_a_remint_is_raised(self) -> None:
        expired = {"success": False, "errors": [{"code": "601", "message": "Access token invalid"}]}
        with scripted_network(
            [
                _token_response("tok-1"),
                ScriptedResponse(json=expired),
                _token_response("tok-2"),
                ScriptedResponse(json=expired),
            ]
        ) as network:
            client = MarketoClient(MUNCHKIN, "client-id", "client-secret")
            with pytest.raises(MarketoTokenError):
                client.request_json("GET", "/rest/v1/campaigns.json")

        assert [request.path for request in network.requests_log].count("/identity/oauth/token") == 2

    def test_identity_endpoint_failure_is_an_auth_error(self) -> None:
        with scripted_network([ScriptedResponse(status=401, json={"error": "invalid_client"})]) as network:
            client = MarketoClient(MUNCHKIN, "client-id", "client-secret")
            with pytest.raises(MarketoAuthError):
                client.access_token()

        assert [request.path for request in network.requests_log] == ["/identity/oauth/token"]

    def test_transport_error_while_minting_a_token_redacts_credentials(self) -> None:
        # A connection/timeout error carries the prepared URL, which embeds the credentials as
        # query params; that string is persisted as the import's latest_error, so both literals
        # must be scrubbed before the error escapes.
        error = requests.ConnectionError(
            "Max retries exceeded with url: /identity/oauth/token?client_id=client-id&client_secret=client-secret"
        )
        with scripted_network(always(error)) as network:
            client = MarketoClient(MUNCHKIN, "client-id", "client-secret")
            with pytest.raises(MarketoAuthError) as excinfo:
                client.access_token()

        message = str(excinfo.value)
        assert "client-secret" not in message
        assert "client-id" not in message
        assert {request.path for request in network.requests_log} == {"/identity/oauth/token"}
        assert network.session_options[0]["redact_values"] == ("client-id", "client-secret")

    @pytest.mark.parametrize(
        "token_body,status,expected_ok",
        [
            (_token_body(), 200, True),
        ],
    )
    def test_validate_credentials_maps_the_identity_probe(
        self, token_body: dict[str, Any], status: int, expected_ok: bool
    ) -> None:
        with scripted_network([ScriptedResponse(status=status, json=token_body)]) as network:
            ok, message = validate_credentials(MUNCHKIN, "client-id", "client-secret")

        assert ok is expected_ok
        assert (message is None) is expected_ok
        assert [request.path for request in network.requests_log] == ["/identity/oauth/token"]

    def test_validate_credentials_rejects_a_malformed_munchkin_id_without_a_request(self) -> None:
        with scripted_network([]) as network:
            ok, message = validate_credentials("not a munchkin", "client-id", "client-secret")

        assert ok is False
        assert message is not None and "Munchkin" in message
        assert network.requests_log == []
        assert network.session_options == []

    def test_token_paging_walks_until_more_result_is_false(self) -> None:
        result = _driver().run(
            "campaigns",
            [
                _token_response(),
                ScriptedResponse(
                    json={"success": True, "result": [{"id": 1}], "nextPageToken": "t2", "moreResult": True}
                ),
                ScriptedResponse(
                    json={"success": True, "result": [{"id": 2}], "nextPageToken": "t3", "moreResult": False}
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]
        assert result.params("nextPageToken") == [None, None, "t2"]
        assert result.saved_states == [MarketoResumeConfig(next_page_token="t2")]
        assert result.final_state is None

    def test_offset_paging_stops_on_the_first_short_page(self) -> None:
        full_page = [{"id": index} for index in range(200)]
        result = _driver().run(
            "programs",
            [
                _token_response(),
                ScriptedResponse(json={"success": True, "result": full_page}),
                ScriptedResponse(json={"success": True, "result": [{"id": 999}]}),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == 201
        assert result.params("offset") == [None, "0", "200"]
        assert result.saved_states == [MarketoResumeConfig(offset=200)]
        assert result.final_state is None

    def test_offset_paging_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "forms",
            [_token_response(), ScriptedResponse(json={"success": True, "result": [{"id": 1}]})],
            resume_state=MarketoResumeConfig(offset=400),
        )

        assert result.raised is None
        assert result.requests[1].param("offset") == "400"
        assert result.rows == [{"id": 1}]

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

    @pytest.mark.parametrize("status", ["Failed", "Cancelled"])
    def test_a_terminal_export_status_fails_the_sync(self, status: str) -> None:
        result = _driver(_recent_start()).run(
            "activities",
            [
                _token_response(),
                ScriptedResponse(json={"success": True, "result": [{"exportId": "exp-1"}]}),
                ScriptedResponse(json={"success": True, "result": [{"exportId": "exp-1"}]}),
                ScriptedResponse(json={"success": True, "result": [{"status": status, "errorMsg": "too much data"}]}),
            ],
        )

        assert isinstance(result.raised, MarketoAPIError)
        assert status in str(result.raised)
        assert "too much data" in str(result.raised)

    def test_a_create_response_without_an_export_id_fails_the_sync(self) -> None:
        result = _driver(_recent_start()).run(
            "activities", [_token_response(), ScriptedResponse(json={"success": True, "result": []})]
        )

        assert isinstance(result.raised, MarketoAPIError)

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

    def test_source_response_items_are_lazy(self) -> None:
        # Building the SourceResponse must not touch the network — the pipeline calls items().
        manager = MarketoSource().get_resumable_source_manager(source_inputs("campaigns"))
        with scripted_network([]) as network:
            marketo_source(MUNCHKIN, "cid", "secret", "campaigns", manager, mock.MagicMock())

        assert network.session_options == []
        assert network.requests_log == []

    def test_list_members_walk_every_list_in_id_order(self) -> None:
        result = _driver().run(
            "list_members",
            [
                _token_response(),
                _ok({"result": [{"id": 20}, {"id": 10}], "nextPageToken": "l2", "moreResult": True}),
                _ok({"result": [{"id": 5}], "moreResult": False}),
                _ok({"result": []}),
                # A page token with no moreResult still means another page.
                _ok({"result": [{"id": 1}], "nextPageToken": "t2"}),
                _ok({"result": [{"id": 2}], "moreResult": False}),
                _ok({"result": [{"id": 3}], "moreResult": False}),
            ],
        )

        assert result.raised is None
        assert result.paths[3:] == [
            "/rest/v1/lists/5/leads.json",
            "/rest/v1/lists/10/leads.json",
            "/rest/v1/lists/10/leads.json",
            "/rest/v1/lists/20/leads.json",
        ]
        assert result.params("nextPageToken")[3:] == [None, None, "t2", None]
        assert result.rows == [{"id": 1, "listId": 10}, {"id": 2, "listId": 10}, {"id": 3, "listId": 20}]
        assert result.saved_states == [
            MarketoResumeConfig(parent_id=5),
            MarketoResumeConfig(parent_id=10, next_page_token="t2"),
            MarketoResumeConfig(parent_id=10),
            MarketoResumeConfig(parent_id=20),
        ]
        assert result.final_state is None
        assert result.response is not None and result.response.sort_mode is None

    @pytest.mark.parametrize(
        "resume,expected_paths,expected_tokens",
        [
            (
                MarketoResumeConfig(parent_id=10, next_page_token="t2"),
                ["/rest/v1/lists/10/leads.json", "/rest/v1/lists/20/leads.json"],
                ["t2", None],
            ),
            (MarketoResumeConfig(parent_id=10), ["/rest/v1/lists/20/leads.json"], [None]),
            # The list the cursor was in is gone, so the next list starts from its first page.
            (MarketoResumeConfig(parent_id=15, next_page_token="t9"), ["/rest/v1/lists/20/leads.json"], [None]),
        ],
    )
    def test_list_members_resume_skips_finished_lists(
        self,
        resume: MarketoResumeConfig,
        expected_paths: list[str],
        expected_tokens: list[Optional[str]],
    ) -> None:
        result = _driver().run(
            "list_members",
            [
                _token_response(),
                _ok({"result": [{"id": 5}, {"id": 10}, {"id": 20}], "moreResult": False}),
                *[_ok({"result": [{"id": 1}], "moreResult": False}) for _ in expected_paths],
            ],
            resume_state=resume,
        )

        assert result.raised is None
        assert result.paths[2:] == expected_paths
        assert result.params("nextPageToken")[2:] == expected_tokens

    def test_program_members_query_each_program_in_seven_day_windows_from_its_creation(self) -> None:
        start = (datetime.now(UTC) - timedelta(days=10)).replace(microsecond=0)
        boundary = start + timedelta(days=7)
        created = (datetime.now(UTC) - timedelta(days=3)).replace(microsecond=0)
        member = {"leadId": 1, "statusName": "Member"}
        result = _driver(format_datetime(start)).run(
            "program_members",
            [
                _token_response(),
                # Asset timestamps carry an offset after the Z.
                _ok(
                    {
                        "result": [
                            {"id": 2, "createdAt": "2015-01-01T00:00:00Z+0000"},
                            {"id": 1, "createdAt": format_datetime(created) + "+0000"},
                        ]
                    }
                ),
                _ok({"result": [{"fields": [{"name": "leadId"}, {"name": "statusName"}]}]}),
                _ok({"result": [{**member, "updatedAt": format_datetime(created)}], "moreResult": False}),
                # A member updated on the boundary comes back from both windows and is kept once.
                _ok({"result": [{**member, "leadId": 2, "updatedAt": format_datetime(boundary)}]}),
                _ok({"result": [{**member, "leadId": 2, "updatedAt": format_datetime(boundary)}]}),
            ],
        )

        assert result.raised is None
        members = [request for request in result.requests if request.path.endswith("/members.json")]
        assert [request.path for request in members] == [
            "/rest/v1/programs/1/members.json",
            "/rest/v1/programs/2/members.json",
            "/rest/v1/programs/2/members.json",
        ]
        assert [request.param("startAt") for request in members] == [
            format_datetime(created),
            format_datetime(start),
            format_datetime(boundary),
        ]
        assert members[1].param("endAt") == format_datetime(boundary)
        assert {request.param("filterType") for request in members} == {"updatedAt"}
        assert members[0].param("fields") == "leadId,programId,membershipDate,updatedAt,statusName"
        assert [(row["programId"], row["leadId"]) for row in result.rows] == [(1, 1), (2, 2)]
        assert [(state.parent_id, state.window_start) for state in result.saved_states] == [
            (1, None),
            (2, format_datetime(boundary)),
            (2, None),
        ]
        assert {state.query_end for state in result.saved_states} == {members[0].param("endAt")}
        assert result.response is not None and result.response.sort_mode is None

    def test_program_members_resume_inside_the_saved_window_with_the_saved_end(self) -> None:
        window_start = format_datetime((datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0))
        query_end = format_datetime((datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0))
        result = _driver().run(
            "program_members",
            [
                _token_response(),
                _ok({"result": [{"id": 1, "createdAt": "2015-01-01T00:00:00Z+0000"}, {"id": 2}]}),
                _ok({"result": []}),
                _ok({"result": [{"leadId": 7, "updatedAt": window_start}], "moreResult": False}),
            ],
            resume_state=MarketoResumeConfig(
                parent_id=2, window_start=window_start, next_page_token="p3", query_end=query_end
            ),
        )

        assert result.raised is None
        assert result.paths[3:] == ["/rest/v1/programs/2/members.json"]
        assert result.params("startAt")[3:] == [window_start]
        assert result.params("endAt")[3:] == [query_end]
        assert result.params("nextPageToken")[3:] == ["p3"]
        assert result.rows == [{"leadId": 7, "updatedAt": window_start, "programId": 2}]
