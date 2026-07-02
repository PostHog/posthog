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
    """Records requested URLs and replays a queue of responses."""

    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.requested_urls: list[str] = []

    def get(self, url: str, headers: dict | None = None, timeout: int | None = None) -> _FakeResponse:
        self.requested_urls.append(url)
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
        assert set(GONG_ENDPOINTS) == {"calls", "users", "scorecards", "workspaces"}
