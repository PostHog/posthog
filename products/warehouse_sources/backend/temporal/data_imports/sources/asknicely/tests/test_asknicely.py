import json
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely import (
    AskNicelyResumeConfig,
    _normalize_row,
    _to_unix_timestamp,
    asknicely_source,
    build_responses_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import RESPONSES_PAGE_SIZE

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely"


def _response(rows: list[dict[str, Any]], total_pages: Optional[int] = None) -> Response:
    body: dict[str, Any] = {"success": True, "data": rows}
    if total_pages is not None:
        body["totalpages"] = str(total_pages)
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps(body).encode()
    return resp


def _manager(resume: Optional[AskNicelyResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[str]:
    """Wire a mock session and capture each request's URL AT PREPARE TIME.

    The paginator mutates ``request.url`` in place across pages, so inspecting it after the run
    shows only the final URL — snapshot it when each request is prepared instead.
    """
    session.headers = {}
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestAsknicely:
    def test_build_responses_url(self) -> None:
        assert build_responses_url("acme", page_number=2, since_time=1700000000) == (
            f"https://acme.asknice.ly/api/v1/responses/asc/{RESPONSES_PAGE_SIZE}/2/1700000000/json/answered/responded"
        )

    @pytest.mark.parametrize("subdomain", ["", "acme.asknice.ly", "a/b", "a b", "-leading"])
    def test_build_responses_url_rejects_invalid_subdomain(self, subdomain: str) -> None:
        with pytest.raises(ValueError):
            build_responses_url(subdomain, page_number=1, since_time=0)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20), 1700000000),
            (date(2023, 11, 14), 1699920000),
        ],
    )
    def test_to_unix_timestamp(self, value: Any, expected: int) -> None:
        assert _to_unix_timestamp(value) == expected

    @pytest.mark.parametrize("value", ["not-a-timestamp", None, True, {"ts": 1}])
    def test_to_unix_timestamp_rejects_unusable_values(self, value: Any) -> None:
        with pytest.raises(ValueError):
            _to_unix_timestamp(value)

    def test_normalize_row_coerces_string_timestamps(self) -> None:
        row = _normalize_row(
            {"response_id": "r1", "responded": "1418692529", "sent": "1418692531", "opened": "0", "comment": "12345"}
        )
        assert row["responded"] == 1418692529
        assert row["sent"] == 1418692531
        assert row["opened"] == 0
        # Non-timestamp fields keep their original type even when digit-like.
        assert row["comment"] == "12345"

    def _run(
        self,
        responses: list[Response],
        manager: mock.MagicMock,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        session = mock.MagicMock()
        urls = _wire(session, responses)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = _rows(
                asknicely_source(
                    subdomain="acme",
                    api_key="key",
                    endpoint="responses",
                    team_id=1,
                    job_id="job-1",
                    resumable_source_manager=manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        return rows, urls

    def test_paginates_until_totalpages_and_normalizes_rows(self) -> None:
        manager = _manager()
        responses = [
            _response([{"response_id": "r1", "responded": "100"}], total_pages=2),
            _response([{"response_id": "r2", "responded": "200"}], total_pages=2),
        ]

        rows, urls = self._run(responses, manager)

        assert [row["response_id"] for row in rows] == ["r1", "r2"]
        # String timestamps are coerced to ints via the data_map.
        assert rows[0]["responded"] == 100
        assert urls == [
            build_responses_url("acme", page_number=1, since_time=0),
            build_responses_url("acme", page_number=2, since_time=0),
        ]
        # Only the intermediate page boundary is checkpointed — never past the final page.
        manager.save_state.assert_called_once_with(AskNicelyResumeConfig(page_number=2, since_time=0))

    def test_stops_on_empty_page_when_totalpages_missing(self) -> None:
        responses = [
            _response([{"response_id": f"r{i}", "responded": "100"} for i in range(RESPONSES_PAGE_SIZE)]),
            _response([]),
        ]

        rows, urls = self._run(responses, _manager())

        assert len(rows) == RESPONSES_PAGE_SIZE
        assert len(urls) == 2

    def test_short_page_without_totalpages_terminates(self) -> None:
        rows, urls = self._run([_response([{"response_id": "r1", "responded": "100"}])], _manager())

        assert [row["response_id"] for row in rows] == ["r1"]
        assert len(urls) == 1

    def test_incremental_since_time_steps_back_one_second(self) -> None:
        _, urls = self._run(
            [_response([])],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )
        assert urls == [build_responses_url("acme", page_number=1, since_time=1699999999)]

    def test_incremental_since_time_clamps_at_zero(self) -> None:
        _, urls = self._run(
            [_response([])],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=0,
        )
        assert urls == [build_responses_url("acme", page_number=1, since_time=0)]

    def test_resumes_from_saved_page_and_cutoff(self) -> None:
        # The saved since_time must win over a freshly derived one: page numbering is only
        # stable against the cutoff the interrupted run used.
        manager = _manager(AskNicelyResumeConfig(page_number=3, since_time=500))

        _, urls = self._run(
            [_response([])],
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert urls == [build_responses_url("acme", page_number=3, since_time=500)]

    def test_no_checkpoint_on_single_short_page(self) -> None:
        # A run that finishes on its first page must never checkpoint — there is no next page.
        manager = _manager()
        self._run([_response([{"response_id": "r1", "responded": "100"}])], manager)
        manager.save_state.assert_not_called()

    def test_sync_session_disables_capture_and_redirects(self) -> None:
        # Survey bodies stay out of HTTP sample capture, and the X-apikey header must never be
        # replayed to a redirect target.
        session = mock.MagicMock()
        _wire(session, [_response([])])
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            _rows(
                asknicely_source(
                    subdomain="acme",
                    api_key="key",
                    endpoint="responses",
                    team_id=1,
                    job_id="job-1",
                    resumable_source_manager=_manager(),
                )
            )
        assert make_session.call_args.kwargs["capture"] is False
        assert make_session.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_session_disables_redirects(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            validate_credentials("acme", "key")
        assert make_session.call_args.kwargs["allow_redirects"] is False
        assert make_session.call_args.kwargs["capture"] is False

    def test_source_response_shape(self) -> None:
        response = asknicely_source(
            subdomain="acme",
            api_key="key",
            endpoint="responses",
            team_id=1,
            job_id="job-1",
            resumable_source_manager=_manager(),
        )

        assert response.name == "responses"
        assert response.primary_keys == ["response_id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["responded"]

    @pytest.mark.parametrize(
        ("status_code", "expected_valid", "expected_message_fragment"),
        [
            (200, True, None),
            (401, False, "Invalid AskNicely API key"),
            (403, False, "Invalid AskNicely API key"),
            (500, False, "unexpected status code: 500"),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_message_fragment: str | None
    ) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, error_message = validate_credentials("acme", "key")

        assert is_valid is expected_valid
        if expected_message_fragment is None:
            assert error_message is None
        else:
            assert error_message is not None and expected_message_fragment in error_message

    def test_validate_credentials_rejects_invalid_subdomain(self) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as mock_session:
            # An invalid subdomain raises inside build_responses_url before any request is made,
            # and validate_credentials swallows it into a (False, message) result.
            is_valid, error_message = validate_credentials("bad domain", "key")

        assert is_valid is False
        assert error_message is not None
        mock_session.return_value.get.assert_not_called()
