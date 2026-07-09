from datetime import UTC, date, datetime
from typing import Any

from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.settings import THINKIFIC_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific import (
    ThinkificResumeConfig,
    ThinkificRetryableError,
    _build_base_params,
    _fetch_page,
    _format_incremental_date,
    get_rows,
    is_valid_subdomain,
    thinkific_source,
    validate_credentials,
)

PATCH_SESSION = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.thinkific.thinkific.make_tracked_session"
)


def _page(items: list[dict[str, Any]], next_page: int | None) -> dict[str, Any]:
    return {"items": items, "meta": {"pagination": {"next_page": next_page}}}


def _mock_response(body: dict[str, Any], status_code: int = 200) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = body
    response.text = str(body)
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError
    return response


def _drive(endpoint: str, manager: MagicMock, responses: list[MagicMock], **kwargs: Any) -> tuple[MagicMock, list[Any]]:
    """Run get_rows with a mocked session, returning (session, yielded_batches)."""
    session = MagicMock()
    session.get.side_effect = responses
    logger = MagicMock()
    with patch(PATCH_SESSION, return_value=session):
        batches = list(
            get_rows(
                api_key="key",
                subdomain="sub",
                endpoint=endpoint,
                logger=logger,
                resumable_source_manager=manager,
                **kwargs,
            )
        )
    return session, batches


class TestFormatIncrementalDate:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 3, 4, 23, 58, tzinfo=UTC), "2026-03-04"),
            ("naive_datetime", datetime(2026, 3, 4, 1, 0), "2026-03-04"),
            ("date", date(2026, 3, 4), "2026-03-04"),
            ("iso_string", "2026-03-04T10:00:00Z", "2026-03-04"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_incremental_date(value) == expected


class TestBuildBaseParams:
    @parameterized.expand(
        [
            # The server-side filter is added only when all three hold: the endpoint supports it, the
            # incremental flag is on, and a cursor value is present. Any other combination is limit-only.
            (
                "incremental_adds_inclusive_filter",
                True,
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"limit": 100, "query[updated_on_or_after]": "2026-03-04"},
            ),
            ("full_refresh_endpoint_never_filters", False, True, datetime(2026, 3, 4, tzinfo=UTC), {"limit": 100}),
            ("cursor_value_missing", True, True, None, {"limit": 100}),
            ("incremental_flag_off", True, False, datetime(2026, 3, 4, tzinfo=UTC), {"limit": 100}),
        ]
    )
    def test_filter_only_added_when_all_conditions_hold(
        self, _name: str, supports_incremental: bool, should_use: bool, value: Any, expected: dict[str, Any]
    ) -> None:
        assert _build_base_params(100, supports_incremental, should_use, value) == expected


class TestIsValidSubdomain:
    @parameterized.expand(
        [
            ("simple", "mycompany", True),
            ("hyphenated", "my-company", True),
            ("alnum", "abc123", True),
            ("with_space", "my company", False),
            ("with_dot", "my.company", False),
            ("with_protocol", "https://x", False),
            ("empty", "", False),
        ]
    )
    def test_subdomain(self, _name: str, value: str, expected: bool) -> None:
        assert is_valid_subdomain(value) is expected


class TestFetchPage:
    # Call the undecorated function so a single status maps straight to its raise, bypassing tenacity's
    # retry/backoff (which would otherwise loop and slow the test).
    _raw = _fetch_page.__wrapped__  # type: ignore[attr-defined]

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("gateway", 503)])
    def test_retryable_status_raises_retryable_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response({}, status_code=status)
        try:
            TestFetchPage._raw(session, "https://x", {}, MagicMock())
            raise AssertionError("expected ThinkificRetryableError")
        except ThinkificRetryableError:
            pass

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_4xx_raises_http_error(self, _name: str, status: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response({"error": "Authentication Error"}, status_code=status)
        try:
            TestFetchPage._raw(session, "https://x", {}, MagicMock())
            raise AssertionError("expected HTTPError")
        except requests.HTTPError:
            pass

    def test_success_returns_json(self) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response(_page([{"id": 1}], None))
        result = TestFetchPage._raw(session, "https://x", {}, MagicMock())
        assert result["items"] == [{"id": 1}]


class TestGetRowsPagination:
    def test_fresh_run_paginates_and_saves_after_each_non_terminal_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [
            _mock_response(_page([{"id": 1}], 2)),
            _mock_response(_page([{"id": 2}], 3)),
            _mock_response(_page([{"id": 3}], None)),
        ]
        session, batches = _drive("courses", manager, responses)

        # Each page is yielded as a list[dict] (no source-level batcher).
        assert batches == [[{"id": 1}], [{"id": 2}], [{"id": 3}]]

        # First page request starts at page=1; subsequent requests advance to the saved next_page.
        sent_pages = [call.args[0] for call in session.get.call_args_list]
        assert "page=1" in sent_pages[0]
        assert "page=2" in sent_pages[1]
        assert "page=3" in sent_pages[2]

        # State saved after each non-terminal page; the terminal page saves nothing.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ThinkificResumeConfig(next_page=2), ThinkificResumeConfig(next_page=3)]

    def test_resume_starts_from_saved_page(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = ThinkificResumeConfig(next_page=5)
        responses = [_mock_response(_page([{"id": 99}], None))]
        session, batches = _drive("courses", manager, responses)

        assert batches == [[{"id": 99}]]
        assert "page=5" in session.get.call_args_list[0].args[0]
        manager.load_state.assert_called_once()

    def test_terminal_single_page_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_mock_response(_page([{"id": 1}], None))]
        _drive("courses", manager, responses)
        manager.save_state.assert_not_called()

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_mock_response(_page([], None))]
        _, batches = _drive("courses", manager, responses)
        assert batches == []

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_mock_response(_page([{"id": 1}], None))]
        _drive("courses", manager, responses)
        manager.load_state.assert_not_called()

    def test_incremental_filter_applied_for_enrollments(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_mock_response(_page([{"id": 1}], None))]
        session, _ = _drive(
            "enrollments",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        url = session.get.call_args_list[0].args[0]
        assert "updated_on_or_after" in url

    def test_no_incremental_filter_for_full_refresh_endpoint(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        responses = [_mock_response(_page([{"id": 1}], None))]
        session, _ = _drive(
            "courses",
            manager,
            responses,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, tzinfo=UTC),
        )
        url = session.get.call_args_list[0].args[0]
        assert "updated_on_or_after" not in url


class TestThinkificSourceResponse:
    def test_full_refresh_endpoint_has_no_partitioning(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        resp = thinkific_source("k", "s", "courses", MagicMock(), manager)
        assert resp.name == "courses"
        assert resp.primary_keys == ["id"]
        assert resp.partition_mode is None
        assert resp.partition_keys is None
        assert resp.sort_mode == "asc"

    def test_enrollments_partitions_by_created_at(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        resp = thinkific_source("k", "s", "enrollments", MagicMock(), manager)
        assert resp.partition_mode == "datetime"
        assert resp.partition_keys == ["created_at"]
        assert resp.partition_format == "month"

    @parameterized.expand(list(THINKIFIC_ENDPOINTS.keys()))
    def test_every_endpoint_builds_a_response(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        resp = thinkific_source("k", "s", endpoint, MagicMock(), manager)
        assert resp.primary_keys == ["id"]
        assert callable(resp.items)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, 200),
            ("unauthorized", 401, False, 401),
            ("forbidden", 403, False, 403),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_valid: bool, expected_code: int) -> None:
        session = MagicMock()
        session.get.return_value = _mock_response({}, status_code=status)
        with patch(PATCH_SESSION, return_value=session):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is expected_valid
        assert code == expected_code

    def test_exception_returns_none_status(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("boom")
        with patch(PATCH_SESSION, return_value=session):
            is_valid, code = validate_credentials("key", "sub")
        assert is_valid is False
        assert code is None
