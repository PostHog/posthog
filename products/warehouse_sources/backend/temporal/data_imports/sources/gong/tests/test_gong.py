import base64
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong import (
    GONG_BASE_URL,
    GongResumeConfig,
    _build_url,
    _format_datetime,
    _get_headers,
    _to_datetime,
    get_rows,
    gong_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.settings import GONG_ENDPOINTS


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            raise Exception(f"{self.status_code} Client Error for url: {GONG_BASE_URL}")


class _FakeSession:
    """Records requested URLs (and POST bodies) and replays a queue of responses."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []
        self.posted_bodies: list[dict | None] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._responses.pop(0)

    def post(
        self, url: str, headers: dict | None = None, json: dict | None = None, timeout: int | None = None
    ) -> _FakeResponse:
        self.requested_urls.append(url)
        self.posted_bodies.append(json)
        return self._responses.pop(0)


class _FakeResumableManager(ResumableSourceManager[GongResumeConfig]):
    """In-memory stand-in for the Redis-backed manager (no `super().__init__`)."""

    def __init__(self, resume_state: GongResumeConfig | None = None):
        self._resume_state = resume_state
        self.saved_states: list[GongResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> GongResumeConfig | None:
        return self._resume_state

    def save_state(self, data: GongResumeConfig) -> None:
        self.saved_states.append(data)


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("utc_aware", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_treated_as_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format_datetime(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_datetime(value) == expected

    def test_no_plus_zero_offset(self) -> None:
        assert "+00:00" not in _format_datetime(datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC))


class TestToDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("aware_datetime", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC)),
            ("date", date(2026, 1, 1), datetime(2026, 1, 1, tzinfo=UTC)),
            ("iso_string", "2026-01-01T00:00:00Z", datetime(2026, 1, 1, tzinfo=UTC)),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime | None) -> None:
        assert _to_datetime(value) == expected


class TestGetHeaders:
    def test_basic_auth_header(self) -> None:
        headers = _get_headers("my-key", "my-secret")
        expected_token = base64.b64encode(b"my-key:my-secret").decode()
        assert headers["Authorization"] == f"Basic {expected_token}"
        assert headers["Accept"] == "application/json"


class TestBuildUrl:
    def test_without_params(self) -> None:
        assert _build_url("/v2/users", {}) == f"{GONG_BASE_URL}/v2/users"

    def test_with_params(self) -> None:
        url = _build_url("/v2/calls", {"cursor": "abc"})
        assert url == f"{GONG_BASE_URL}/v2/calls?cursor=abc"


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True, None),
            ("unauthorized", 401, None, False, "Invalid Gong access key or access key secret"),
            ("forbidden_source_create", 403, None, True, None),
            (
                "forbidden_for_schema",
                403,
                "calls",
                False,
                "Your Gong credentials do not have permission to access this endpoint",
            ),
        ]
    )
    def test_validate_credentials(
        self, _name: str, status_code: int, schema_name: str | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        session = _FakeSession([_FakeResponse(status_code=status_code)])
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            is_valid, message = validate_credentials("key", "secret", schema_name)

        assert is_valid is expected_valid
        assert message == expected_message
        assert session.requested_urls == [f"{GONG_BASE_URL}/v2/workspaces"]


class TestCursorPagination:
    def test_paginates_until_cursor_absent(self) -> None:
        responses = [
            _FakeResponse(json_data={"users": [{"id": "1"}], "records": {"cursor": "abc"}}),
            _FakeResponse(json_data={"users": [{"id": "2"}]}),
        ]
        session = _FakeSession(responses)
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows("key", "secret", "users", mock.MagicMock(), manager))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert session.requested_urls == [
            f"{GONG_BASE_URL}/v2/users",
            f"{GONG_BASE_URL}/v2/users?cursor=abc",
        ]
        # Non-windowed endpoints do not persist resume state.
        assert manager.saved_states == []

    def test_single_page_without_records(self) -> None:
        session = _FakeSession([_FakeResponse(json_data={"workspaces": [{"id": "w1"}]})])
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(get_rows("key", "secret", "workspaces", mock.MagicMock(), manager))

        assert batches == [[{"id": "w1"}]]
        assert session.requested_urls == [f"{GONG_BASE_URL}/v2/workspaces"]


class TestWindowedCalls:
    def test_single_window_incremental(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        session = _FakeSession([_FakeResponse(json_data={"calls": [{"id": "c1"}]})])
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    "key",
                    "secret",
                    "calls",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )

        assert batches == [[{"id": "c1"}]]
        # Exactly one window (last_value is within the 90-day cap of now).
        assert len(session.requested_urls) == 1
        assert f"fromDateTime={_format_datetime(last_value)}" in unquote(session.requested_urls[0])
        # State saved once after the window completes.
        assert len(manager.saved_states) == 1

    def test_cursor_within_window(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        responses = [
            _FakeResponse(json_data={"calls": [{"id": "c1"}], "records": {"cursor": "page2"}}),
            _FakeResponse(json_data={"calls": [{"id": "c2"}]}),
        ]
        session = _FakeSession(responses)
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    "key",
                    "secret",
                    "calls",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )

        assert batches == [[{"id": "c1"}], [{"id": "c2"}]]
        assert "cursor=page2" in session.requested_urls[1]

    @parameterized.expand(
        [
            # Gong signals an empty date window with a 404; the sync skips it and continues.
            (
                "no_calls_body_skips_window",
                '{"errors":["No calls found corresponding to the provided filters"]}',
                False,
            ),
            # A 404 for any other reason must still surface rather than be swallowed.
            ("unrelated_404_raises", '{"errors":["Not Found"]}', True),
        ]
    )
    def test_404_handling(self, _name: str, body: str, should_raise: bool) -> None:
        last_value = datetime.now(UTC) - timedelta(days=100)
        responses = [
            _FakeResponse(status_code=404, text=body),
            _FakeResponse(json_data={"calls": [{"id": "c1"}]}),
        ]
        session = _FakeSession(responses)
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            rows = get_rows(
                "key",
                "secret",
                "calls",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=last_value,
            )
            if should_raise:
                with pytest.raises(Exception):
                    list(rows)
                return
            batches = list(rows)

        # The empty window yields nothing but does not abort the sync; both windows run.
        assert batches == [[{"id": "c1"}]]
        assert len(session.requested_urls) == 2
        assert len(manager.saved_states) == 2

    def test_resume_uses_saved_window_start(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=80)
        resume_start = datetime.now(UTC) - timedelta(days=10)
        session = _FakeSession([_FakeResponse(json_data={"calls": [{"id": "c1"}]})])
        manager = _FakeResumableManager(resume_state=GongResumeConfig(window_start=_format_datetime(resume_start)))

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    "key",
                    "secret",
                    "calls",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )

        # The first request starts from the resumed window, not the DB cursor value.
        assert f"fromDateTime={_format_datetime(resume_start)}" in unquote(session.requested_urls[0])


class TestGongSource:
    @parameterized.expand(
        [
            ("calls", "id", "started", "asc"),
            ("transcripts", "callId", "started", "asc"),
            ("users", "id", "created", "asc"),
            ("scorecards", "scorecardId", "created", "asc"),
            ("workspaces", "id", None, "asc"),
        ]
    )
    def test_source_response_shape(
        self, endpoint: str, primary_key: str, partition_key: str | None, sort_mode: str
    ) -> None:
        response = gong_source("key", "secret", endpoint, mock.MagicMock(), _FakeResumableManager())

        assert response.name == endpoint
        assert response.primary_keys == [primary_key]
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None

    def test_every_endpoint_has_a_config(self) -> None:
        assert set(GONG_ENDPOINTS) == {
            "calls",
            "calls_extensive",
            "transcripts",
            "users",
            "scorecards",
            "workspaces",
        }


class TestExtensiveCalls:
    def test_posts_extensive_body_and_flattens_metadata(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        session = _FakeSession(
            [
                _FakeResponse(
                    json_data={
                        "calls": [
                            {
                                "metaData": {"id": "c1", "title": "Discovery", "started": "2026-03-01T00:00:00Z"},
                                "parties": [{"emailAddress": "buyer@acme.com", "affiliation": "External"}],
                                "context": [{"system": "Salesforce", "objects": [{"objectType": "Account"}]}],
                            }
                        ]
                    }
                )
            ]
        )
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    "key",
                    "secret",
                    "calls_extensive",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )

        # metaData is lifted to the top level; parties and CRM context ride along as columns.
        assert batches == [
            [
                {
                    "id": "c1",
                    "title": "Discovery",
                    "started": "2026-03-01T00:00:00Z",
                    "parties": [{"emailAddress": "buyer@acme.com", "affiliation": "External"}],
                    "context": [{"system": "Salesforce", "objects": [{"objectType": "Account"}]}],
                }
            ]
        ]
        # A single POST to the extensive endpoint with no query string.
        assert session.requested_urls == [f"{GONG_BASE_URL}/v2/calls/extensive"]
        body = session.posted_bodies[0]
        assert body is not None
        assert body["contentSelector"] == {"context": "Extended", "exposedFields": {"parties": True}}
        assert body["filter"]["fromDateTime"] == _format_datetime(last_value)
        assert "cursor" not in body

    def test_cursor_travels_in_body(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        session = _FakeSession(
            [
                _FakeResponse(json_data={"calls": [{"metaData": {"id": "c1"}}], "records": {"cursor": "page2"}}),
                _FakeResponse(json_data={"calls": [{"metaData": {"id": "c2"}}]}),
            ]
        )
        manager = _FakeResumableManager()

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    "key",
                    "secret",
                    "calls_extensive",
                    mock.MagicMock(),
                    manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )

        assert batches == [
            [{"id": "c1", "parties": None, "context": None}],
            [{"id": "c2", "parties": None, "context": None}],
        ]
        # The cursor is sent in the second request's body, never as a query param.
        second_body = session.posted_bodies[1]
        assert second_body is not None
        assert second_body["cursor"] == "page2"
        assert all("?" not in url for url in session.requested_urls)

    @parameterized.expand(
        [
            # Extensive responses carry participant names and free-form CRM fields, and transcript
            # responses carry verbatim conversation text, so neither may reach HTTP sample capture.
            # Basic list endpoints stay captured for troubleshooting.
            ("calls_extensive", [{"calls": [{"metaData": {"id": "c1"}}]}], False),
            (
                "transcripts",
                [{"calls": [{"id": "c1", "started": "2026-03-01T00:00:00Z"}]}, {"callTranscripts": [{"callId": "c1"}]}],
                False,
            ),
            ("users", [{"users": [{"id": "u1"}]}], True),
        ]
    )
    def test_response_body_capture_per_endpoint(
        self, endpoint: str, payloads: list[dict], expected_capture: bool
    ) -> None:
        session = _FakeSession([_FakeResponse(json_data=payload) for payload in payloads])

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ) as session_factory:
            list(
                get_rows(
                    "key",
                    "secret",
                    endpoint,
                    mock.MagicMock(),
                    _FakeResumableManager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=5),
                )
            )

        assert session_factory.call_args.kwargs["capture"] is expected_capture


class TestTranscripts:
    def test_drives_from_calls_and_stamps_each_transcript_with_its_call_start(self) -> None:
        last_value = datetime.now(UTC) - timedelta(days=5)
        session = _FakeSession(
            [
                _FakeResponse(
                    json_data={
                        "calls": [{"id": "c1", "started": "2026-03-01T00:00:00Z"}],
                        "records": {"cursor": "calls-page2"},
                    }
                ),
                _FakeResponse(json_data={"callTranscripts": [{"callId": "c1", "transcript": [{"speakerId": "u1"}]}]}),
                _FakeResponse(json_data={"calls": [{"id": "c2", "started": "2026-03-02T00:00:00Z"}]}),
                _FakeResponse(json_data={"callTranscripts": [{"callId": "c2", "transcript": []}]}),
            ]
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            batches = list(
                get_rows(
                    "key",
                    "secret",
                    "transcripts",
                    mock.MagicMock(),
                    _FakeResumableManager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=last_value,
                )
            )

        # `started` comes from the call the transcript belongs to — the transcript response has no
        # date of its own, so without it the table can't sync incrementally or partition.
        assert batches == [
            [{"callId": "c1", "transcript": [{"speakerId": "u1"}], "started": "2026-03-01T00:00:00Z"}],
            [{"callId": "c2", "transcript": [], "started": "2026-03-02T00:00:00Z"}],
        ]
        # Every page of the calls walk drives its own transcript request, so a second page of calls
        # isn't dropped.
        assert f"fromDateTime={_format_datetime(last_value)}" in unquote(session.requested_urls[0])
        assert session.requested_urls[1] == f"{GONG_BASE_URL}/v2/calls/transcript"
        assert "cursor=calls-page2" in session.requested_urls[2]
        assert session.requested_urls[3] == f"{GONG_BASE_URL}/v2/calls/transcript"
        # Each request asks only for the ids on the page that drove it.
        assert [body["filter"]["callIds"] for body in session.posted_bodies if body] == [["c1"], ["c2"]]

    @parameterized.expand(
        [
            # A call with no start time leaves its transcript with nothing to partition or sync on.
            ("call_without_start_time", [{"id": "c1"}], [{"callId": "c1"}]),
            # A transcript for a call we never asked for has no start time to borrow either.
            (
                "transcript_for_unrequested_call",
                [{"id": "c1", "started": "2026-03-01T00:00:00Z"}],
                [{"callId": "other"}],
            ),
        ]
    )
    def test_unstampable_transcript_stops_the_sync(
        self, _name: str, calls: list[dict], transcripts: list[dict]
    ) -> None:
        session = _FakeSession(
            [
                _FakeResponse(json_data={"calls": calls}),
                _FakeResponse(json_data={"callTranscripts": transcripts}),
            ]
        )

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.gong.gong.make_tracked_session",
            return_value=session,
        ):
            rows = get_rows(
                "key",
                "secret",
                "transcripts",
                mock.MagicMock(),
                _FakeResumableManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=5),
            )
            # Writing the row with `started=None` would bury it in the fallback partition and keep
            # it out of the watermark, so no later run would ever correct it.
            with pytest.raises(ValueError):
                list(rows)
