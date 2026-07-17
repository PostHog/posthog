import json
import datetime as dt
from typing import Any, cast

import pytest
from freezegun import freeze_time
from unittest import mock

from django.db import OperationalError

from requests.exceptions import JSONDecodeError as RequestsJSONDecodeError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MetaAdsSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads import meta_ads as meta_ads_module
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads import (
    MALFORMED_JSON_MAX_ATTEMPTS,
    META_ADS_MAX_HISTORY_DAYS,
    META_AUTH_ERROR_MESSAGE,
    PAGE_LIMIT_FALLBACK_SIZES,
    MetaAdsResumeConfig,
    _earliest_supported_since,
    _fetch_integration_row,
    _is_permanent_auth_error,
    _iter_simple_pagination,
    _iter_time_range_pagination,
    _next_smaller_limit,
    _override_limit,
    _strip_access_token,
    get_integration,
    meta_ads_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.source import MetaAdsSource
from products.warehouse_sources.backend.types import IncrementalFieldType


def _mock_response(status: int, body: dict) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = ""
    return response


def _mock_truncated_response() -> mock.MagicMock:
    # Meta occasionally returns HTTP 200 with a truncated JSON body, so `.json()`
    # raises JSONDecodeError even though the status is healthy. requests raises its
    # own JSONDecodeError (subclass of simplejson's, not the stdlib json's, when
    # simplejson is installed), so mirror that here rather than the stdlib type.
    response = mock.MagicMock()
    response.status_code = 200
    response.json.side_effect = RequestsJSONDecodeError("Unterminated string starting at", "{", 98254)
    response.text = '{"data": [{"id": "1"'
    return response


def _build_manager(*, can_resume: bool = False, state: MetaAdsResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestStripAccessToken:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "https://graph.facebook.com/v20/next?access_token=secret&cursor=abc",
                "https://graph.facebook.com/v20/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v20/next?cursor=abc&access_token=secret",
                "https://graph.facebook.com/v20/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v20/next?access_token=secret",
                "https://graph.facebook.com/v20/next",
            ),
            (
                "https://graph.facebook.com/v20/next?cursor=abc",
                "https://graph.facebook.com/v20/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v20/next",
                "https://graph.facebook.com/v20/next",
            ),
            (
                # Multiple access_token params (pathological) — all removed.
                "https://example/path?access_token=a&foo=1&access_token=b",
                "https://example/path?foo=1",
            ),
        ],
    )
    def test_strips(self, url: str, expected: str) -> None:
        assert _strip_access_token(url) == expected


class TestSimplePagination:
    INITIAL_URL = "https://graph.facebook.com/v20/act_123/campaigns"
    INITIAL_PARAMS: dict[str, Any] = {"fields": "id,name", "access_token": "tok"}

    def test_fresh_run_fetches_initial_and_saves_next_url(self) -> None:
        manager = _build_manager()

        responses = [
            _mock_response(
                200,
                {
                    "data": [{"id": "1"}, {"id": "2"}],
                    "paging": {"next": "https://graph.facebook.com/v20/next?access_token=tok&cursor=abc"},
                },
            ),
            _mock_response(200, {"data": [{"id": "3"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    self.INITIAL_PARAMS,
                    None,
                    manager,
                )
            )

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        # First call: initial URL + params.
        assert mock_get.return_value.get.call_args_list[0].args[0] == self.INITIAL_URL
        assert mock_get.return_value.get.call_args_list[0].kwargs["params"] == self.INITIAL_PARAMS
        # Second call: the saved (token-stripped) URL plus access_token supplied via params.
        # Using the stripped URL for the fetch too prevents `requests` from sending duplicate
        # `access_token` query parameters.
        assert mock_get.return_value.get.call_args_list[1].args[0] == "https://graph.facebook.com/v20/next?cursor=abc"
        assert mock_get.return_value.get.call_args_list[1].kwargs["params"] == {"access_token": "tok"}

        # Saved state: access_token stripped from the saved URL.
        manager.save_state.assert_called_once_with(
            MetaAdsResumeConfig(next_url="https://graph.facebook.com/v20/next?cursor=abc")
        )

    def test_resume_skips_initial_request(self) -> None:
        # Saved URL has access_token stripped; we re-inject a fresh one at request time.
        saved_url = "https://graph.facebook.com/v20/next?cursor=xyz"
        manager = _build_manager(can_resume=True, state=MetaAdsResumeConfig(next_url=saved_url))

        responses = [
            _mock_response(200, {"data": [{"id": "5"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    self.INITIAL_PARAMS,
                    MetaAdsResumeConfig(next_url=saved_url),
                    manager,
                )
            )

        assert batches == [[{"id": "5"}]]
        assert mock_get.return_value.get.call_count == 1
        assert mock_get.return_value.get.call_args_list[0].args[0] == saved_url
        # access_token is supplied via params (from config), NOT embedded in the saved URL.
        assert mock_get.return_value.get.call_args_list[0].kwargs["params"] == {"access_token": "tok"}
        # No more pages, no save call needed.
        manager.save_state.assert_not_called()

    def test_single_page_does_not_save_state(self) -> None:
        manager = _build_manager()

        responses = [
            _mock_response(200, {"data": [{"id": "1"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as _mock_session_factory:
            _mock_session_factory.return_value.get.side_effect = responses
            batches = list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    {"access_token": "tok"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"id": "1"}]]
        manager.save_state.assert_not_called()

    def test_ignores_resume_state_when_time_range_mode(self) -> None:
        # A time-range-mode state (end_date set) should NOT be consumed by simple pagination.
        manager = _build_manager()
        stale_state = MetaAdsResumeConfig(
            next_url="https://example/ignored",
            end_date="2026-01-01",
            chunk_since="2025-12-15",
            chunk_size_days=30,
        )

        responses = [_mock_response(200, {"data": [], "paging": {}})]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            list(
                _iter_simple_pagination(
                    self.INITIAL_URL,
                    {"access_token": "tok"},
                    stale_state,
                    manager,
                )
            )

        # Initial request should be the original URL with params, not the stale next_url.
        assert mock_get.return_value.get.call_args_list[0].args[0] == self.INITIAL_URL
        assert mock_get.return_value.get.call_args_list[0].kwargs["params"] == {"access_token": "tok"}


class TestSimplePaginationLimitFallback:
    INITIAL_URL = "https://graph.facebook.com/v20/act_123/campaigns"
    # Mirrors production params from `meta_ads_source`: a default page limit is always set.
    PARAMS: dict[str, Any] = {"fields": "id,name", "limit": 500, "access_token": "tok"}
    REDUCE_BODY: dict[str, Any] = {
        "error": {"code": 1, "message": "Please reduce the amount of data you're asking for, then retry your request"}
    }

    def test_initial_too_much_data_retries_with_smaller_limit(self) -> None:
        manager = _build_manager()
        responses = [
            # Initial request at the default limit is rejected as too large.
            _mock_response(500, self.REDUCE_BODY),
            # Retry at the next-smaller limit succeeds.
            _mock_response(200, {"data": [{"id": "1"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        assert batches == [[{"id": "1"}]]
        # First attempt used the default 500 limit.
        assert mock_get.return_value.get.call_args_list[0].args[0] == self.INITIAL_URL
        assert mock_get.return_value.get.call_args_list[0].kwargs["params"]["limit"] == 500
        # Retry re-issues the same initial URL with the limit reduced to the next rung (100).
        assert mock_get.return_value.get.call_args_list[1].args[0] == self.INITIAL_URL
        assert mock_get.return_value.get.call_args_list[1].kwargs["params"]["limit"] == 100

    def test_cursor_too_much_data_retries_with_smaller_limit(self) -> None:
        manager = _build_manager()
        responses = [
            # Page 1 succeeds and hands back a cursor.
            _mock_response(
                200,
                {"data": [{"id": "1"}], "paging": {"next": "https://graph.facebook.com/v20/next?after=p1"}},
            ),
            # The cursor request is rejected as too large at the default limit.
            _mock_response(500, self.REDUCE_BODY),
            # Retry of the SAME cursor at a smaller limit succeeds; no more pages.
            _mock_response(200, {"data": [{"id": "2"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        # Cursor first tried without a limit override (still at the default).
        assert mock_get.return_value.get.call_args_list[1].args[0] == "https://graph.facebook.com/v20/next?after=p1"
        # Retry uses the SAME cursor with the limit reduced to 100.
        assert (
            mock_get.return_value.get.call_args_list[2].args[0]
            == "https://graph.facebook.com/v20/next?after=p1&limit=100"
        )

    def test_exhausting_limit_ladder_raises(self) -> None:
        manager = _build_manager()
        # Every rung in PAGE_LIMIT_FALLBACK_SIZES returns the too-much-data error.
        responses = [_mock_response(500, self.REDUCE_BODY) for _ in PAGE_LIMIT_FALLBACK_SIZES]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            with pytest.raises(Exception, match="Meta API request failed: 500"):
                list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        # One attempt per rung, then it gives up.
        assert mock_get.return_value.get.call_count == len(PAGE_LIMIT_FALLBACK_SIZES)

    def test_non_timeout_error_does_not_retry(self) -> None:
        manager = _build_manager()
        # Transient service error (code 2) — not a too-much-data error, so no limit fallback.
        responses = [_mock_response(500, {"error": {"message": "Service temporarily unavailable", "code": 2}})]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            with pytest.raises(Exception, match="Meta API request failed: 500"):
                list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        assert mock_get.return_value.get.call_count == 1


class TestSimplePaginationMalformedJson:
    INITIAL_URL = "https://graph.facebook.com/v20/act_123/campaigns"
    PARAMS: dict[str, Any] = {"fields": "id,name", "limit": 500, "access_token": "tok"}

    def test_initial_truncated_body_reissues_same_request(self) -> None:
        manager = _build_manager()
        responses = [
            # Initial request comes back 200 but with a truncated JSON body.
            _mock_truncated_response(),
            # Re-issuing the same request returns a complete body.
            _mock_response(200, {"data": [{"id": "1"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        assert batches == [[{"id": "1"}]]
        # Re-issue targets the same initial URL (no rows were yielded before the retry).
        assert mock_get.return_value.get.call_count == 2
        assert mock_get.return_value.get.call_args_list[1].args[0] == self.INITIAL_URL

    def test_cursor_truncated_body_reissues_same_cursor(self) -> None:
        manager = _build_manager()
        responses = [
            _mock_response(
                200,
                {"data": [{"id": "1"}], "paging": {"next": "https://graph.facebook.com/v20/next?after=p1"}},
            ),
            # The cursor page returns a truncated body, then succeeds on re-issue.
            _mock_truncated_response(),
            _mock_response(200, {"data": [{"id": "2"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        # The already-yielded first page is not re-emitted; the cursor is re-fetched.
        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        assert mock_get.return_value.get.call_args_list[1].args[0] == "https://graph.facebook.com/v20/next?after=p1"
        assert mock_get.return_value.get.call_args_list[2].args[0] == "https://graph.facebook.com/v20/next?after=p1"

    def test_persistently_truncated_body_raises(self) -> None:
        manager = _build_manager()
        responses = [_mock_truncated_response() for _ in range(MALFORMED_JSON_MAX_ATTEMPTS)]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            with pytest.raises(RequestsJSONDecodeError):
                list(_iter_simple_pagination(self.INITIAL_URL, self.PARAMS, None, manager))

        # Bounded: one attempt per allowed try, then it gives up (stays retryable upstream).
        assert mock_get.return_value.get.call_count == MALFORMED_JSON_MAX_ATTEMPTS


class TestTimeRangePagination:
    URL = "https://graph.facebook.com/v20/act_1/insights"
    PARAMS: dict[str, Any] = {"fields": "ad_id", "limit": 500, "level": "ad", "access_token": "tok"}

    def test_fresh_run_saves_chunk_state_after_first_page(self) -> None:
        manager = _build_manager()
        # One 1-day window (since == until), one page with a paging.next, then done.
        responses = [
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "a"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?access_token=tok&after=abc"},
                },
            ),
            _mock_response(200, {"data": [{"ad_id": "b"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-04-21", "until": "2026-04-21"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"ad_id": "a"}], [{"ad_id": "b"}]]
        # Two saves: mid-chunk next_url, then the chunk-boundary (past end_date) save.
        assert manager.save_state.call_count == 2
        mid_chunk: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert mid_chunk.end_date == "2026-04-21"
        assert mid_chunk.chunk_since == "2026-04-21"
        assert mid_chunk.chunk_size_days == 30
        # Saved URL has access_token stripped.
        assert mid_chunk.chunk_next_url == "https://graph.facebook.com/v20/act_1/insights?after=abc"

        final: MetaAdsResumeConfig = manager.save_state.call_args_list[1].args[0]
        assert final.chunk_since == "2026-04-22"
        assert final.chunk_next_url is None

        # Second request uses the stripped URL plus access_token via params (no duplicate token).
        assert (
            mock_get.return_value.get.call_args_list[1].args[0]
            == "https://graph.facebook.com/v20/act_1/insights?after=abc&limit=500"
        )
        assert mock_get.return_value.get.call_args_list[1].kwargs["params"] == {"access_token": "tok"}

    def test_fresh_run_saves_chunk_boundary_between_chunks(self) -> None:
        manager = _build_manager()
        # Two 30-day chunks back to back, each with one page.
        responses = [
            _mock_response(200, {"data": [{"ad_id": "a"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "b"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as _mock_session_factory:
            _mock_session_factory.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-03-01", "until": "2026-04-29"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"ad_id": "a"}], [{"ad_id": "b"}]]
        # After chunk 1 we save pointing at chunk 2; after chunk 2 we save the past-end cursor.
        assert manager.save_state.call_count == 2
        first: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert first.end_date == "2026-04-29"
        assert first.chunk_since == "2026-03-31"  # chunk 1 covered 2026-03-01..2026-03-30 (30 days)
        assert first.chunk_size_days == 30
        assert first.chunk_next_url is None

        final: MetaAdsResumeConfig = manager.save_state.call_args_list[1].args[0]
        assert final.chunk_since == "2026-04-30"  # one past end_date
        assert final.chunk_next_url is None

    def test_past_end_date_chunk_saved_after_final_chunk(self) -> None:
        """After the final chunk completes, we must save a chunk-boundary cursor
        with ``chunk_since > end_date`` — otherwise a stale mid-chunk next_url
        from an earlier iteration (or no state at all) could cause a resume to
        re-process pages that were already yielded."""
        manager = _build_manager()
        responses = [_mock_response(200, {"data": [{"ad_id": "only"}], "paging": {}})]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as _mock_session_factory:
            _mock_session_factory.return_value.get.side_effect = responses
            list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
                )
            )

        assert manager.save_state.call_count == 1
        saved: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert saved.chunk_since == "2026-04-22"
        assert saved.chunk_next_url is None

    def test_resume_past_end_date_cursor_is_noop(self) -> None:
        """If resume state already says ``chunk_since > end_date``, the generator
        must finish without issuing any HTTP request (the sync already ran to
        completion before the crash)."""
        state = MetaAdsResumeConfig(
            end_date="2026-04-21",
            chunk_since="2026-04-22",
            chunk_size_days=30,
            chunk_next_url=None,
        )
        manager = _build_manager(can_resume=True, state=state)

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-10", "until": "2026-04-21"}, state, manager
                )
            )

        assert batches == []
        mock_get.assert_not_called()

    def test_resume_mid_chunk_skips_initial_request(self) -> None:
        saved_next = "https://graph.facebook.com/v20/act_1/insights?after=xyz"
        # End date matches the end of the resumed chunk so no further chunks are fetched.
        state = MetaAdsResumeConfig(
            end_date="2026-04-16",
            chunk_since="2026-04-10",
            chunk_size_days=7,
            chunk_next_url=saved_next,
        )
        manager = _build_manager(can_resume=True, state=state)

        responses = [_mock_response(200, {"data": [{"ad_id": "c"}], "paging": {}})]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-01-01", "until": "2026-04-16"}, state, manager
                )
            )

        assert batches == [[{"ad_id": "c"}]]
        # Two requests: the resumed mid-chunk URL, then nothing more to fetch within this chunk.
        # (There is a final "past end_date" save_state, but no additional HTTP call is made.)
        assert mock_get.return_value.get.call_count == 1
        assert mock_get.return_value.get.call_args_list[0].args[0] == saved_next + "&limit=500"
        # access_token is injected fresh — never served from the saved URL.
        assert mock_get.return_value.get.call_args_list[0].kwargs["params"] == {"access_token": "tok"}

    def test_resume_at_chunk_boundary_issues_fresh_initial_request(self) -> None:
        state = MetaAdsResumeConfig(
            end_date="2026-04-21",
            chunk_since="2026-04-10",
            chunk_size_days=7,
            chunk_next_url=None,
        )
        manager = _build_manager(can_resume=True, state=state)

        responses = [
            _mock_response(200, {"data": [{"ad_id": "d"}], "paging": {}}),
            _mock_response(200, {"data": [], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-01-01", "until": "2026-04-21"}, state, manager
                )
            )

        # First request must be a fresh initial with params embedding the chunk time_range.
        first_call = mock_get.return_value.get.call_args_list[0]
        assert first_call.args[0] == self.URL
        sent_params = first_call.kwargs["params"]
        assert sent_params["access_token"] == "tok"
        # time_range should be JSON-encoded and cover 2026-04-10..2026-04-16 (7 days).
        tr = json.loads(sent_params["time_range"])
        assert tr == {"since": "2026-04-10", "until": "2026-04-16"}

    def test_empty_chunk_still_iterates_to_next(self) -> None:
        manager = _build_manager()
        responses = [
            _mock_response(200, {"data": [], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "x"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as _mock_session_factory:
            _mock_session_factory.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-03-01", "until": "2026-04-29"},
                    None,
                    manager,
                )
            )

        assert batches == [[], [{"ad_id": "x"}]]

    def test_timeout_fallback_shrinks_chunk_size(self) -> None:
        manager = _build_manager()
        timeout_body = {"error": {"error_subcode": 1504018, "message": "timeout"}}
        # 30-day chunk times out, then 7-day chunks succeed.
        # 2026-03-01..2026-03-30 is one 30-day attempt that fails.
        # After fallback: 7-day chunks: 03-01..03-07, 03-08..03-14, 03-15..03-21, 03-22..03-28, 03-29..03-30.
        responses = [
            _mock_response(500, timeout_body),
            _mock_response(200, {"data": [{"ad_id": "1"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "2"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "3"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "4"}], "paging": {}}),
            _mock_response(200, {"data": [{"ad_id": "5"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-03-01", "until": "2026-03-30"}, None, manager
                )
            )

        assert [b[0]["ad_id"] for b in batches] == ["1", "2", "3", "4", "5"]
        # Subsequent saves should all record chunk_size_days=7.
        for call in manager.save_state.call_args_list:
            saved: MetaAdsResumeConfig = call.args[0]
            assert saved.chunk_size_days == 7
        # The first successful request was for a 7-day chunk.
        tr = json.loads(mock_get.return_value.get.call_args_list[1].kwargs["params"]["time_range"])
        assert tr == {"since": "2026-03-01", "until": "2026-03-07"}


class TestOverrideLimit:
    @pytest.mark.parametrize(
        "url,limit,expected",
        [
            (
                "https://graph.facebook.com/v20/x?after=abc",
                100,
                "https://graph.facebook.com/v20/x?after=abc&limit=100",
            ),
            (
                # Existing limit is replaced (not duplicated).
                "https://graph.facebook.com/v20/x?after=abc&limit=500",
                50,
                "https://graph.facebook.com/v20/x?after=abc&limit=50",
            ),
            (
                "https://graph.facebook.com/v20/x?limit=500&after=abc",
                100,
                "https://graph.facebook.com/v20/x?after=abc&limit=100",
            ),
            (
                "https://graph.facebook.com/v20/x",
                100,
                "https://graph.facebook.com/v20/x?limit=100",
            ),
        ],
    )
    def test_overrides(self, url: str, limit: int, expected: str) -> None:
        assert _override_limit(url, limit) == expected


class TestNextSmallerLimit:
    @pytest.mark.parametrize(
        "current,expected",
        [
            (500, 100),
            (100, 50),
            # Smallest rung — no further fallback available.
            (50, None),
            # Non-standard limit between rungs picks the largest rung below it.
            (250, 100),
            # Non-standard limit below the smallest rung — exhausted.
            (10, None),
            # Non-standard limit above the largest rung steps down to the largest rung.
            (1000, 500),
        ],
    )
    def test_step(self, current: int, expected: int | None) -> None:
        assert _next_smaller_limit(current) == expected


class TestMidChunkLimitFallback:
    URL = "https://graph.facebook.com/v20/act_1/insights"
    PARAMS: dict[str, Any] = {"fields": "ad_id", "limit": 500, "level": "ad", "access_token": "tok"}

    def test_mid_chunk_timeout_retries_with_smaller_limit_and_persists(self) -> None:
        manager = _build_manager()
        timeout_body = {"error": {"error_subcode": 1504018, "message": "timeout"}}
        responses = [
            # Initial chunk request returns page 1 + a cursor.
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "1"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?after=p1"},
                },
            ),
            # Cursor request times out at the default limit.
            _mock_response(500, timeout_body),
            # Retry with smaller limit succeeds.
            _mock_response(200, {"data": [{"ad_id": "2"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-04-21", "until": "2026-04-21"},
                    None,
                    manager,
                )
            )

        assert batches == [[{"ad_id": "1"}], [{"ad_id": "2"}]]

        # Initial request used the default 500 limit.
        first_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert first_params["limit"] == 500
        # Second request (the timeout one) used limit=500 on the cursor URL.
        assert (
            mock_get.return_value.get.call_args_list[1].args[0]
            == "https://graph.facebook.com/v20/act_1/insights?after=p1&limit=500"
        )
        # Retry uses the SAME cursor with limit reduced to the next rung (100).
        assert (
            mock_get.return_value.get.call_args_list[2].args[0]
            == "https://graph.facebook.com/v20/act_1/insights?after=p1&limit=100"
        )

        # The mid-chunk save (before the cursor request) recorded chunk_limit=None
        # because the limit hadn't been shrunk yet at save time.
        mid_chunk: MetaAdsResumeConfig = manager.save_state.call_args_list[0].args[0]
        assert mid_chunk.chunk_next_url == "https://graph.facebook.com/v20/act_1/insights?after=p1"
        assert mid_chunk.chunk_limit is None

        # After retry succeeds and the chunk completes, the chunk-boundary save
        # records the reduced limit (100) so future resumes inherit it.
        final: MetaAdsResumeConfig = manager.save_state.call_args_list[-1].args[0]
        assert final.chunk_limit == 100
        assert final.chunk_next_url is None

    def test_resume_honors_chunk_limit_for_mid_chunk_url(self) -> None:
        saved_cursor = "https://graph.facebook.com/v20/act_1/insights?after=resume"
        state = MetaAdsResumeConfig(
            end_date="2026-04-21",
            chunk_since="2026-04-21",
            chunk_size_days=1,
            chunk_next_url=saved_cursor,
            chunk_limit=50,
        )
        manager = _build_manager(can_resume=True, state=state)
        responses = [_mock_response(200, {"data": [{"ad_id": "x"}], "paging": {}})]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, state, manager
                )
            )

        # The resumed cursor was reissued with the persisted limit (50), not the default 500.
        assert mock_get.return_value.get.call_args_list[0].args[0] == saved_cursor + "&limit=50"

    def test_resume_honors_chunk_limit_for_initial_chunk_request(self) -> None:
        # When resume state has chunk_limit but no chunk_next_url, the fresh
        # initial chunk request must also use the reduced limit.
        state = MetaAdsResumeConfig(
            end_date="2026-04-21",
            chunk_since="2026-04-21",
            chunk_size_days=1,
            chunk_next_url=None,
            chunk_limit=100,
        )
        manager = _build_manager(can_resume=True, state=state)
        responses = [_mock_response(200, {"data": [{"ad_id": "y"}], "paging": {}})]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, state, manager
                )
            )

        sent_params = mock_get.return_value.get.call_args_list[0].kwargs["params"]
        assert sent_params["limit"] == 100

    def test_exhausting_limit_ladder_raises(self) -> None:
        manager = _build_manager()
        timeout_body = {"error": {"error_subcode": 1504018, "message": "timeout"}}
        responses = [
            # Initial chunk: page 1 + cursor.
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "1"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?after=p1"},
                },
            ),
            # All limits in PAGE_LIMIT_FALLBACK_SIZES time out.
            *[_mock_response(500, timeout_body) for _ in PAGE_LIMIT_FALLBACK_SIZES],
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            gen = _iter_time_range_pagination(
                self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
            )
            # Drain the first batch (which succeeds), then expect the failure.
            assert next(gen) == [{"ad_id": "1"}]
            with pytest.raises(Exception, match="Meta API request failed: 500"):
                list(gen)

    def test_non_timeout_mid_chunk_error_does_not_retry(self) -> None:
        manager = _build_manager()
        responses = [
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "1"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?after=p1"},
                },
            ),
            # Transient service error (code 2) — not a timeout and not an auth error, so it
            # neither retries-with-smaller-limit nor gets reclassified as permanent.
            _mock_response(500, {"error": {"message": "Service temporarily unavailable", "code": 2}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            gen = _iter_time_range_pagination(
                self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
            )
            assert next(gen) == [{"ad_id": "1"}]
            with pytest.raises(Exception, match="Meta API request failed: 500"):
                list(gen)

        # Exactly two requests: initial + the failed cursor. No retry happened.
        assert mock_get.return_value.get.call_count == 2

    def test_permanent_auth_error_raises_clean_message_and_does_not_retry(self) -> None:
        manager = _build_manager()
        responses = [
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "1"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?after=p1"},
                },
            ),
            # code 190 — invalidated session. Re-auth is the only fix, so no retry should happen.
            _mock_response(
                400,
                {"error": {"message": "Error validating access token", "type": "OAuthException", "code": 190}},
            ),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            gen = _iter_time_range_pagination(
                self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
            )
            assert next(gen) == [{"ad_id": "1"}]
            with pytest.raises(Exception, match="Please re-authorize the integration"):
                list(gen)

        # Initial + failed cursor only — the limit ladder is not exercised for auth errors.
        assert mock_get.return_value.get.call_count == 2


class TestTimeRangeMalformedJson:
    URL = "https://graph.facebook.com/v20/act_1/insights"
    PARAMS: dict[str, Any] = {"fields": "ad_id", "limit": 500, "level": "ad", "access_token": "tok"}

    def test_initial_chunk_truncated_body_reissues_chunk_request(self) -> None:
        manager = _build_manager()
        responses = [
            # Initial chunk request returns a truncated 200 body.
            _mock_truncated_response(),
            # Re-issuing the same chunk request returns a complete body.
            _mock_response(200, {"data": [{"ad_id": "a"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
                )
            )

        assert batches == [[{"ad_id": "a"}]]
        # Both calls are the same initial chunk request, carrying the time_range param.
        assert mock_get.return_value.get.call_count == 2
        for call in mock_get.return_value.get.call_args_list:
            assert call.args[0] == self.URL
            assert json.loads(call.kwargs["params"]["time_range"]) == {"since": "2026-04-21", "until": "2026-04-21"}

    def test_cursor_truncated_body_reissues_same_cursor(self) -> None:
        manager = _build_manager()
        responses = [
            _mock_response(
                200,
                {
                    "data": [{"ad_id": "a"}],
                    "paging": {"next": "https://graph.facebook.com/v20/act_1/insights?after=p1"},
                },
            ),
            # The cursor page returns a truncated body, then succeeds on re-issue.
            _mock_truncated_response(),
            _mock_response(200, {"data": [{"ad_id": "b"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
                )
            )

        # Already-yielded first page is not re-emitted; the cursor is re-fetched at the same limit.
        assert batches == [[{"ad_id": "a"}], [{"ad_id": "b"}]]
        assert (
            mock_get.return_value.get.call_args_list[1].args[0]
            == "https://graph.facebook.com/v20/act_1/insights?after=p1&limit=500"
        )
        assert (
            mock_get.return_value.get.call_args_list[2].args[0]
            == "https://graph.facebook.com/v20/act_1/insights?after=p1&limit=500"
        )

    def test_resumed_cursor_truncated_body_reissues_same_cursor(self) -> None:
        # Mid-chunk resume: pending_next_url comes from a saved MetaAdsResumeConfig,
        # so chunk_params stays None and recovery must go through the last_paging_url branch.
        resumed_cursor = "https://graph.facebook.com/v20/act_1/insights?after=resumed"
        manager = _build_manager(
            can_resume=True,
            state=MetaAdsResumeConfig(
                end_date="2026-04-21",
                chunk_since="2026-04-21",
                chunk_size_days=1,
                chunk_next_url=resumed_cursor,
            ),
        )
        responses = [
            # The resumed cursor page returns a truncated body, then succeeds on re-issue.
            _mock_truncated_response(),
            _mock_response(200, {"data": [{"ad_id": "b"}], "paging": {}}),
        ]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            batches = list(
                _iter_time_range_pagination(
                    self.URL,
                    self.PARAMS,
                    {"since": "2026-04-21", "until": "2026-04-21"},
                    MetaAdsResumeConfig(
                        end_date="2026-04-21",
                        chunk_since="2026-04-21",
                        chunk_size_days=1,
                        chunk_next_url=resumed_cursor,
                    ),
                    manager,
                )
            )

        assert batches == [[{"ad_id": "b"}]]
        # Both calls re-fetch the same resumed cursor at the default limit; no initial chunk request.
        assert mock_get.return_value.get.call_count == 2
        for call in mock_get.return_value.get.call_args_list:
            assert call.args[0] == f"{resumed_cursor}&limit=500"

    def test_persistently_truncated_body_raises(self) -> None:
        manager = _build_manager()
        responses = [_mock_truncated_response() for _ in range(MALFORMED_JSON_MAX_ATTEMPTS)]

        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.meta_ads.meta_ads.make_tracked_session"
        ) as mock_get:
            mock_get.return_value.get.side_effect = responses
            with pytest.raises(RequestsJSONDecodeError):
                list(
                    _iter_time_range_pagination(
                        self.URL, self.PARAMS, {"since": "2026-04-21", "until": "2026-04-21"}, None, manager
                    )
                )

        assert mock_get.return_value.get.call_count == MALFORMED_JSON_MAX_ATTEMPTS


class TestNonRetryableErrors:
    @pytest.mark.parametrize(
        "error_message",
        [
            # Token refresh failure raised by get_integration.
            "Failed to refresh token for Meta Ads integration. Please re-authorize the integration.",
            # Integration row deleted/de-authorized while the source still references it —
            # get_integration raises Django's Integration.DoesNotExist with this message.
            "Integration matching query does not exist.",
            # 400 from Meta when the ad account no longer belongs to the authorised user.
            'Meta API request failed: 400 - {"error":{"message":"(#200) Ad account owner has NOT granted ads_management or ads_read permission.","type":"OAuthException","code":200}}',
            # 400 when a specific endpoint cannot be accessed with the granted permissions.
            'Meta API request failed: 400 - {"error":{"message":"(#100) This endpoint cannot be loaded due to missing permissions."}}',
            # 500 when Meta's backend refuses to service the query even after adaptive
            # chunking has shrunk the window to its smallest size.
            'Meta API request failed: 500 - {"error":{"code":1,"message":"Please reduce the amount of data you\'re asking for, then retry your request"}}',
            # code 190 / subcode 459 — account checkpoint, the user must log in to Facebook.
            f"{META_AUTH_ERROR_MESSAGE} (Meta API response: 400 - "
            '{"error":{"message":"You cannot access the app till you log in to www.facebook.com and follow the '
            'instructions given.","type":"OAuthException","code":190,"error_subcode":459}})',
            # code 190 / subcode 460 — session invalidated after a password change.
            f"{META_AUTH_ERROR_MESSAGE} (Meta API response: 400 - "
            '{"error":{"message":"Error validating access token: The session has been invalidated because the '
            "user changed their password or Facebook has changed the session for security "
            'reasons.","type":"OAuthException","code":190,"error_subcode":460}})',
        ],
    )
    def test_errors_match_pattern(self, error_message: str) -> None:
        patterns = MetaAdsSource().get_non_retryable_errors()
        assert any(pattern in error_message for pattern in patterns), (
            f"Meta Ads error '{error_message}' does not match any non-retryable pattern"
        )

    @pytest.mark.parametrize(
        "body,expected",
        [
            # Permanent auth/permission failures.
            ({"error": {"code": 190, "error_subcode": 459}}, True),
            ({"error": {"code": 190, "error_subcode": 460}}, True),
            ({"error": {"code": 102}}, True),
            ({"error": {"code": 10}}, True),
            ({"error": {"code": 200}}, True),
            ({"error": {"code": 299}}, True),
            # Transient / retryable errors — Meta still tags some of these OAuthException.
            ({"error": {"code": 2, "type": "OAuthException"}}, False),
            ({"error": {"code": 1, "error_subcode": 99}}, False),
            ({"error": {"code": 4}}, False),
            ({"error": {}}, False),
            ({}, False),
        ],
    )
    def test_is_permanent_auth_error(self, body: dict, expected: bool) -> None:
        assert _is_permanent_auth_error(_mock_response(400, body)) is expected


@freeze_time("2026-06-16")
class TestTimeRangeClamping:
    """Meta rejects insights time ranges starting beyond ~37 months (error 3018).

    The `since` we build must stay inside Meta's supported window, even when it is
    derived from an aged incremental cursor.

    The date is frozen so the ``today`` captured in the test and the
    ``dt.date.today()`` read inside ``get_rows`` always agree (no midnight race).
    """

    def _capture_time_range(self, monkeypatch, **source_kwargs: Any) -> dict | None:
        integration = mock.MagicMock()
        integration.access_token = "token"
        monkeypatch.setattr(meta_ads_module, "get_integration", lambda config, team_id: integration)

        captured: dict[str, Any] = {}

        def fake_request(url, params, access_token, time_range, resumable_source_manager):
            captured["time_range"] = time_range
            yield from ()

        monkeypatch.setattr(meta_ads_module, "_make_paginated_api_request", fake_request)

        config = mock.MagicMock()
        config.account_id = "act_123"
        config.meta_ads_integration_id = 1
        config.sync_lookback_days = source_kwargs.pop("sync_lookback_days", None)

        response = meta_ads_source(
            resource_name="campaign_stats",
            config=config,
            team_id=1,
            resumable_source_manager=_build_manager(),
            **source_kwargs,
        )
        list(cast(Any, response.items()))
        return captured["time_range"]

    @pytest.mark.parametrize(
        "days_ago,should_clamp",
        [
            # A dormant account's stored cursor has aged past Meta's 37-month limit.
            (META_ADS_MAX_HISTORY_DAYS + 200, True),
            # A recent cursor sits comfortably inside the supported window.
            (5, False),
        ],
    )
    def test_incremental_cursor_clamping(self, monkeypatch, days_ago: int, should_clamp: bool) -> None:
        today = dt.date.today()
        cursor = today - dt.timedelta(days=days_ago)

        time_range = self._capture_time_range(
            monkeypatch,
            should_use_incremental_field=True,
            incremental_field="date_start",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=cursor,
        )

        assert time_range is not None
        expected_since = _earliest_supported_since(today) if should_clamp else cursor
        assert time_range["since"] == expected_since.strftime("%Y-%m-%d")
        assert time_range["until"] == today.strftime("%Y-%m-%d")

    def test_stats_lookback_is_clamped_to_supported_window(self, monkeypatch) -> None:
        today = dt.date.today()

        time_range = self._capture_time_range(
            monkeypatch,
            sync_lookback_days=10_000,  # capped to META_ADS_MAX_HISTORY_DAYS upstream
            should_use_incremental_field=False,
        )

        assert time_range is not None
        assert time_range["since"] == _earliest_supported_since(today).strftime("%Y-%m-%d")


class TestGetIntegration:
    def test_refreshes_stale_db_connection_before_query(self, monkeypatch) -> None:
        # `get_integration` runs lazily inside `get_rows` on a worker thread whose
        # pooled Django connection may have been closed server-side, surfacing as
        # `OperationalError: the connection is closed`. We must drop the stale
        # connection before querying, so the read happens on a fresh connection.
        calls: list[str] = []

        monkeypatch.setattr(meta_ads_module, "close_old_connections", lambda: calls.append("close_old_connections"))

        integration = mock.MagicMock()

        def fake_get(*args: Any, **kwargs: Any) -> mock.MagicMock:
            calls.append("Integration.objects.get")
            return integration

        monkeypatch.setattr(meta_ads_module.Integration.objects, "get", fake_get)

        meta_ads_integration = mock.MagicMock()
        meta_ads_integration.integration = integration
        integration.errors = None
        monkeypatch.setattr(meta_ads_module, "MetaAdsIntegration", lambda _integration: meta_ads_integration)

        config = MetaAdsSourceConfig(account_id="act_123", meta_ads_integration_id=42)
        result = get_integration(config, team_id=1)

        assert calls == ["close_old_connections", "Integration.objects.get"]
        meta_ads_integration.refresh_access_token.assert_called_once()
        assert result is integration


class TestFetchIntegrationRowDbResilience:
    def test_retries_on_dropped_connection_then_succeeds(self, monkeypatch) -> None:
        integration = object()
        get = mock.Mock(side_effect=[OperationalError("server closed the connection unexpectedly"), integration])
        close = mock.Mock()
        monkeypatch.setattr(meta_ads_module.Integration.objects, "get", get)
        monkeypatch.setattr(meta_ads_module, "close_old_connections", close)
        monkeypatch.setattr(meta_ads_module.time, "sleep", lambda _s: None)

        result = _fetch_integration_row(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 2
        # Evicted up front, then again after the failed query marked the connection unusable.
        assert close.call_count == 2

    def test_rides_out_pool_wait_timeout_then_succeeds(self, monkeypatch) -> None:
        integration = object()
        get = mock.Mock(
            side_effect=[
                OperationalError("query_wait_timeout"),
                OperationalError("query_wait_timeout"),
                integration,
            ]
        )
        sleeps: list[int] = []
        monkeypatch.setattr(meta_ads_module.Integration.objects, "get", get)
        monkeypatch.setattr(meta_ads_module, "close_old_connections", lambda: None)
        monkeypatch.setattr(meta_ads_module.time, "sleep", lambda s: sleeps.append(s))

        result = _fetch_integration_row(integration_id=1, team_id=2)

        assert result is integration
        assert get.call_count == 3
        # Backoff grows per attempt per `min(2 * attempt, 30)`: 2s after the 1st failure, 4s after the 2nd.
        assert sleeps == [2, 4]

    def test_reraises_after_exhausting_attempts(self, monkeypatch) -> None:
        get = mock.Mock(side_effect=OperationalError("query_wait_timeout"))
        sleeps: list[int] = []
        monkeypatch.setattr(meta_ads_module.Integration.objects, "get", get)
        monkeypatch.setattr(meta_ads_module, "close_old_connections", lambda: None)
        monkeypatch.setattr(meta_ads_module.time, "sleep", lambda s: sleeps.append(s))

        with pytest.raises(OperationalError):
            _fetch_integration_row(integration_id=1, team_id=2)

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry the activity.
        assert get.call_count == 4
        # Backed off between each attempt (2s, 4s, 6s) but not after the final attempt that re-raises.
        assert sleeps == [2, 4, 6]

    def test_missing_integration_is_not_retried(self, monkeypatch) -> None:
        get = mock.Mock(side_effect=meta_ads_module.Integration.DoesNotExist())
        monkeypatch.setattr(meta_ads_module.Integration.objects, "get", get)
        monkeypatch.setattr(meta_ads_module, "close_old_connections", lambda: None)
        monkeypatch.setattr(meta_ads_module.time, "sleep", lambda _s: None)

        with pytest.raises(meta_ads_module.Integration.DoesNotExist):
            _fetch_integration_row(integration_id=1, team_id=2)

        # A deleted integration row is non-retryable — don't mask it as a transient drop.
        assert get.call_count == 1
