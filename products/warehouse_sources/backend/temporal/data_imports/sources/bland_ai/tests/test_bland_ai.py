from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.bland_ai import (
    BASE_URL,
    PAGE_SIZE,
    BlandAIResumeConfig,
    _format_start_date,
    bland_ai_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import ENDPOINTS

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.bland_ai"


def _calls_url(offset: int, start_date: str | None = None) -> str:
    params: dict[str, Any] = {"from": offset, "limit": PAGE_SIZE, "ascending": "true", "sort_by": "created_at"}
    if start_date:
        params["start_date"] = start_date
    return f"{BASE_URL}/v1/calls?{urlencode(params)}"


def _make_manager(resume_state: BlandAIResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(json_body: Any, status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = json_body
    resp.status_code = status
    resp.ok = status < 400
    return resp


def _url_router(responses: dict[str, Any]) -> Any:
    """Return a session.get side_effect that maps each requested URL to a mocked response."""

    def fake_get(url: str, headers: Any = None, timeout: Any = None) -> mock.MagicMock:
        return _resp(responses[url])

    return fake_get


class TestFormatStartDate:
    @parameterized.expand(
        [
            ("none", None, None),
            # A naive watermark is stamped UTC so the server-side filter is unambiguous.
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), "2026-01-02T03:04:05+00:00"),
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), "2026-01-02T03:04:05+00:00"),
            ("date", date(2026, 1, 2), "2026-01-02"),
            ("iso_string", "2026-01-02T03:04:05+00:00", "2026-01-02T03:04:05+00:00"),
        ]
    )
    def test_format_start_date(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_start_date(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False), ("error", 500, False)]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            mock_session.return_value.get.return_value = _resp({}, status=status_code)
            assert validate_credentials("key") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session: mock.MagicMock) -> None:
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_sends_raw_api_key_in_authorization_header(self, mock_session: mock.MagicMock) -> None:
        # Bland expects the raw key, not a "Bearer "-prefixed value.
        mock_session.return_value.get.return_value = _resp({}, status=200)
        validate_credentials("sk-raw-key")
        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["authorization"] == "sk-raw-key"


class TestGetCallRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_by_offset_until_total_count(self, mock_session: mock.MagicMock) -> None:
        page_one = [{"call_id": f"c{i}", "created_at": "2026-01-01T00:00:00+00:00"} for i in range(PAGE_SIZE)]
        page_two = [{"call_id": "clast", "created_at": "2026-01-02T00:00:00+00:00"}]
        responses = {
            _calls_url(0): {"total_count": PAGE_SIZE + 1, "count": PAGE_SIZE, "calls": page_one},
            _calls_url(PAGE_SIZE): {"total_count": PAGE_SIZE + 1, "count": 1, "calls": page_two},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager()
        batches = list(get_rows("key", "calls", mock.MagicMock(), manager))

        assert [len(b) for b in batches] == [PAGE_SIZE, 1]
        assert batches[1][0]["call_id"] == "clast"
        # Reaching total_count terminates without requesting a third page.
        assert mock_session.return_value.get.call_count == 2

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_stops_on_empty_page_when_total_count_overcounts(self, mock_session: mock.MagicMock) -> None:
        # total_count can drift from what's actually returned; an empty page must still terminate.
        responses = {
            _calls_url(0): {"total_count": 50, "count": 2, "calls": [{"call_id": "c1"}, {"call_id": "c2"}]},
            _calls_url(2): {"total_count": 50, "count": 0, "calls": []},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        batches = list(get_rows("key", "calls", mock.MagicMock(), _make_manager()))

        assert [len(b) for b in batches] == [2]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_incremental_watermark_becomes_start_date_filter(self, mock_session: mock.MagicMock) -> None:
        watermark = datetime(2026, 1, 5, tzinfo=UTC)
        url = _calls_url(0, start_date="2026-01-05T00:00:00+00:00")
        responses = {url: {"total_count": 1, "count": 1, "calls": [{"call_id": "c1"}]}}
        mock_session.return_value.get.side_effect = _url_router(responses)

        batches = list(
            get_rows(
                "key",
                "calls",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=watermark,
            )
        )

        # The router KeyErrors on any URL without the start_date filter, so reaching here proves
        # the watermark was sent server-side.
        assert [r["call_id"] for b in batches for r in b] == ["c1"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_saves_state_after_each_page_with_filter(self, mock_session: mock.MagicMock) -> None:
        start_date = "2026-01-05T00:00:00+00:00"
        responses = {
            _calls_url(0, start_date): {"total_count": 3, "count": 2, "calls": [{"call_id": "c1"}, {"call_id": "c2"}]},
            _calls_url(2, start_date): {"total_count": 3, "count": 1, "calls": [{"call_id": "c3"}]},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "calls",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 5, tzinfo=UTC),
            )
        )

        # State is saved once (after page one; page two hits total_count) and carries both the next
        # offset and the exact filter, so a resume continues the same result set.
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.offset == 2
        assert saved.start_date == start_date

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset_and_filter(self, mock_session: mock.MagicMock) -> None:
        saved_filter = "2026-01-05T00:00:00+00:00"
        responses = {
            _calls_url(2, saved_filter): {"total_count": 3, "count": 1, "calls": [{"call_id": "c3"}]},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager(BlandAIResumeConfig(offset=2, start_date=saved_filter))
        batches = list(
            get_rows(
                "key",
                "calls",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                # The checkpointed watermark has advanced past the interrupted run's filter; the
                # resumed run must reuse the saved filter or the saved offset points at the wrong rows.
                db_incremental_field_last_value=datetime(2026, 1, 7, tzinfo=UTC),
            )
        )

        assert [r["call_id"] for b in batches for r in b] == ["c3"]

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_account_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        responses = {_calls_url(0): {"total_count": 0, "count": 0, "calls": []}}
        mock_session.return_value.get.side_effect = _url_router(responses)

        manager = _make_manager()
        assert list(get_rows("key", "calls", mock.MagicMock(), manager)) == []
        manager.save_state.assert_not_called()


class TestGetCallTranscriptRows:
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_hydrates_each_call_and_injects_parent_keys(self, mock_session: mock.MagicMock) -> None:
        responses = {
            _calls_url(0): {
                "total_count": 2,
                "count": 2,
                "calls": [
                    {"call_id": "c1", "created_at": "2026-01-01T00:00:00+00:00"},
                    {"call_id": "c2", "created_at": "2026-01-02T00:00:00+00:00"},
                ],
            },
            f"{BASE_URL}/v1/calls/c1": {
                "call_id": "c1",
                "transcripts": [
                    {"id": 1, "text": "hello", "user": "assistant", "created_at": "2026-01-01T00:00:01+00:00"},
                    {"id": 2, "text": "hi", "user": "user", "created_at": "2026-01-01T00:00:05+00:00"},
                ],
            },
            # A call with no transcripts (e.g. unanswered) must not break the batch.
            f"{BASE_URL}/v1/calls/c2": {"call_id": "c2", "transcripts": None},
        }
        mock_session.return_value.get.side_effect = _url_router(responses)

        batches = list(get_rows("key", "call_transcripts", mock.MagicMock(), _make_manager()))
        rows = [row for batch in batches for row in batch]

        assert [r["id"] for r in rows] == [1, 2]
        # Rows carry the parent call id (composite primary key) and the parent's creation time
        # (the incremental/partition field — utterance timestamps aren't monotonic across calls).
        assert all(r["call_id"] == "c1" for r in rows)
        assert all(r["call_created_at"] == "2026-01-01T00:00:00+00:00" for r in rows)
        assert rows[0]["text"] == "hello"


class TestGetPathwayRows:
    @parameterized.expand(
        [
            # Bare list of pathway objects.
            ("bare_list", [{"id": "p1"}, {"id": "p2"}], ["p1", "p2"]),
            # Wrapped list variants.
            ("wrapped_pathways", {"pathways": [{"id": "p1"}]}, ["p1"]),
            ("wrapped_data", {"data": [{"id": "p1"}]}, ["p1"]),
            # A single bare object (the shape the docs' response example shows).
            ("single_object", {"id": "p1", "name": "Demo", "nodes": []}, ["p1"]),
        ]
    )
    def test_normalizes_response_shapes(self, _name: str, api_response: Any, expected_ids: list[str]) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            responses = {f"{BASE_URL}/v1/pathway": api_response}
            mock_session.return_value.get.side_effect = _url_router(responses)

            batches = list(get_rows("key", "pathways", mock.MagicMock(), _make_manager()))
            rows = [row for batch in batches for row in batch]

            assert [r["id"] for r in rows] == expected_ids

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_pathway_list_yields_nothing(self, mock_session: mock.MagicMock) -> None:
        responses: dict[str, Any] = {f"{BASE_URL}/v1/pathway": []}
        mock_session.return_value.get.side_effect = _url_router(responses)

        assert list(get_rows("key", "pathways", mock.MagicMock(), _make_manager())) == []


class TestBlandAISourceResponse:
    def test_endpoints_inventory(self) -> None:
        assert ENDPOINTS == ("calls", "call_transcripts", "pathways")

    @parameterized.expand(
        [
            ("calls", ["call_id"], ["created_at"]),
            # The composite key keeps utterances unique table-wide; partitioning uses the parent
            # call's stable creation time.
            ("call_transcripts", ["call_id", "id"], ["call_created_at"]),
            ("pathways", ["id"], None),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_keys: list[str]) -> None:
        response = bland_ai_source("key", endpoint, mock.MagicMock(), _make_manager())
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.partition_keys == partition_keys
        assert response.partition_mode == ("datetime" if partition_keys else None)
        # Call listings request ascending=true&sort_by=created_at.
        assert response.sort_mode == "asc"
