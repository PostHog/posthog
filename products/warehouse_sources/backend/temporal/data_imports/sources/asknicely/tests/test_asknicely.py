from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely import (
    AskNicelyResumeConfig,
    _normalize_row,
    _to_unix_timestamp,
    asknicely_source,
    build_responses_url,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.settings import RESPONSES_PAGE_SIZE

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.asknicely.asknicely"


def _page(rows: list[dict[str, Any]], total_pages: Optional[int] = None) -> mock.MagicMock:
    response = mock.MagicMock()
    response.ok = True
    response.status_code = 200
    body: dict[str, Any] = {"success": True, "data": rows}
    if total_pages is not None:
        body["totalpages"] = str(total_pages)
    response.json.return_value = body
    return response


def _manager(resume: Optional[AskNicelyResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    return manager


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
        pages: list[mock.MagicMock],
        manager: mock.MagicMock,
        should_use_incremental_field: bool = False,
        db_incremental_field_last_value: Any = None,
    ) -> tuple[list[list[dict[str, Any]]], list[str]]:
        session = mock.MagicMock()
        session.get.side_effect = pages
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    subdomain="acme",
                    api_key="key",
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=should_use_incremental_field,
                    db_incremental_field_last_value=db_incremental_field_last_value,
                )
            )
        urls = [call.args[0] for call in session.get.call_args_list]
        return batches, urls

    def test_paginates_until_totalpages_and_normalizes_rows(self) -> None:
        manager = _manager()
        pages = [
            _page([{"response_id": "r1", "responded": "100"}], total_pages=2),
            _page([{"response_id": "r2", "responded": "200"}], total_pages=2),
        ]

        batches, urls = self._run(pages, manager)

        assert [row["response_id"] for batch in batches for row in batch] == ["r1", "r2"]
        assert batches[0][0]["responded"] == 100
        assert urls == [
            build_responses_url("acme", page_number=1, since_time=0),
            build_responses_url("acme", page_number=2, since_time=0),
        ]
        # Only the intermediate page boundary is checkpointed — never past the final page.
        manager.save_state.assert_called_once_with(AskNicelyResumeConfig(page_number=2, since_time=0))

    def test_stops_on_empty_page_when_totalpages_missing(self) -> None:
        pages = [
            _page([{"response_id": "r1", "responded": "100"}] * RESPONSES_PAGE_SIZE),
            _page([]),
        ]

        batches, urls = self._run(pages, _manager())

        assert len(batches) == 1
        assert len(urls) == 2

    def test_short_page_without_totalpages_terminates(self) -> None:
        batches, urls = self._run([_page([{"response_id": "r1", "responded": "100"}])], _manager())

        assert len(batches) == 1
        assert len(urls) == 1

    def test_incremental_since_time_steps_back_one_second(self) -> None:
        _, urls = self._run(
            [_page([])],
            _manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )
        assert urls == [build_responses_url("acme", page_number=1, since_time=1699999999)]

    def test_incremental_since_time_clamps_at_zero(self) -> None:
        _, urls = self._run(
            [_page([])],
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
            [_page([])],
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=1700000000,
        )

        assert urls == [build_responses_url("acme", page_number=3, since_time=500)]

    def test_state_saved_only_after_yield(self) -> None:
        # A crash mid-batch must re-yield the last page on resume, not skip it — so the
        # checkpoint may only be written once the batch has been handed to the pipeline.
        manager = _manager()
        session = mock.MagicMock()
        session.get.side_effect = [
            _page([{"response_id": "r1", "responded": "100"}], total_pages=2),
            _page([{"response_id": "r2", "responded": "200"}], total_pages=2),
        ]

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            rows = get_rows(
                subdomain="acme",
                api_key="key",
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
            )
            next(rows)
            manager.save_state.assert_not_called()
            next(rows)
            manager.save_state.assert_called_once_with(AskNicelyResumeConfig(page_number=2, since_time=0))

    def test_sync_session_disables_redirects(self) -> None:
        # The X-apikey header must never be replayed to a redirect target.
        session = mock.MagicMock()
        session.get.side_effect = [_page([])]
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            list(
                get_rows(
                    subdomain="acme",
                    api_key="key",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_manager(),
                )
            )
        assert make_session.call_args.kwargs["allow_redirects"] is False

    def test_validate_credentials_session_disables_redirects(self) -> None:
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=200)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            validate_credentials("acme", "key")
        assert make_session.call_args.kwargs["allow_redirects"] is False

    def test_source_response_shape(self) -> None:
        response = asknicely_source(
            subdomain="acme",
            api_key="key",
            endpoint="responses",
            logger=mock.MagicMock(),
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
            is_valid, error_message = validate_credentials("bad domain", "key")

        assert is_valid is False
        assert error_message is not None
        mock_session.return_value.get.assert_not_called()
