import hmac
import hashlib
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional, cast
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http.url_utils import scrub_url
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.facebook_pages import (
    AUTH_ERROR_PREFIX,
    INTEGRATION_KIND,
    MAX_ACCOUNT_PAGES,
    PERMISSION_ERROR_PREFIX,
    FacebookPagesAPIError,
    FacebookPagesAuthError,
    FacebookPagesInvalidPageIdError,
    FacebookPagesPermissionError,
    FacebookPagesResumeConfig,
    FacebookPagesRetryableError,
    FacebookPagesTokenRefreshError,
    _to_epoch_seconds,
    appsecret_proof,
    facebook_pages_source,
    flatten_insights,
    get_rows,
    get_user_access_token,
    graph_url,
    list_pages,
    raise_for_graph_error,
    resolve_page_access_token,
    unsupported_metrics,
    validate_credentials,
    validated_page_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.settings import (
    DEFAULT_INSIGHTS_LOOKBACK_DAYS,
    FACEBOOK_PAGES_ENDPOINTS,
    INSIGHTS_WINDOW_DAYS,
    PAGE_INSIGHTS_METRICS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.facebook_pages.facebook_pages"

PAGE_ID = "123456789012345"
USER_TOKEN = "user-token"
PAGE_TOKEN = "page-token"
API_VERSION = "v23.0"

NOW = 1_700_000_000
SECONDS_PER_DAY = 24 * 60 * 60


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _response(
    *, status_code: int = 200, json_data: Any = None, headers: Optional[dict[str, str]] = None
) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.text = ""
    response.json.return_value = json_data
    response.headers = headers or {}
    return response


class _FakeSession:
    """Returns canned responses in order and records every requested URL."""

    def __init__(self, responses: list[mock.MagicMock]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> mock.MagicMock:
        self.urls.append(url)
        if not self._responses:
            raise AssertionError(f"unexpected extra request to {url}")
        return self._responses.pop(0)


class _FakeManager(ResumableSourceManager[FacebookPagesResumeConfig]):
    def __init__(self, resume: FacebookPagesResumeConfig | None = None) -> None:
        self._resume = resume
        self.saved: list[FacebookPagesResumeConfig] = []

    def can_resume(self) -> bool:
        return self._resume is not None

    def load_state(self) -> FacebookPagesResumeConfig | None:
        return self._resume

    def save_state(self, data: FacebookPagesResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self._resume = None


def _query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def _run(
    endpoint: str,
    session: _FakeSession,
    manager: _FakeManager,
    **kwargs: Any,
) -> list[list[dict[str, Any]]]:
    with (
        mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
        mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        mock.patch(f"{MODULE}._now_seconds", return_value=NOW),
    ):
        return list(
            get_rows(
                page_id=PAGE_ID,
                access_token=USER_TOKEN,
                endpoint=endpoint,
                api_version=API_VERSION,
                logger=mock.MagicMock(),
                resumable_source_manager=manager,
                **kwargs,
            )
        )


class TestRequestSigning:
    def test_graph_url_pins_the_api_version(self) -> None:
        assert graph_url("v23.0", f"{PAGE_ID}/posts") == f"https://graph.facebook.com/v23.0/{PAGE_ID}/posts"

    def test_token_rides_in_the_header_not_the_query_string(self) -> None:
        session = _FakeSession([_response(json_data={"data": [], "paging": {}})])
        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        ):
            list(
                get_rows(
                    page_id=PAGE_ID,
                    access_token=USER_TOKEN,
                    endpoint="posts",
                    api_version=API_VERSION,
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeManager(),
                )
            )

        assert PAGE_TOKEN not in session.urls[0]
        assert USER_TOKEN not in session.urls[0]


class TestSampleCaptureDisabled:
    """Graph responses carry arbitrary Page content the scrubber can't recognise, so the
    tracked sessions must be built with capture=False on both the sync and probe paths."""

    def test_sync_path_disables_sample_capture(self) -> None:
        session = _FakeSession([_response(json_data={"data": [], "paging": {}})])
        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session,
            mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        ):
            list(
                get_rows(
                    page_id=PAGE_ID,
                    access_token=USER_TOKEN,
                    endpoint="posts",
                    api_version=API_VERSION,
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeManager(),
                )
            )

        assert make_session.call_args.kwargs["capture"] is False

    def test_probe_path_disables_sample_capture(self) -> None:
        session = _FakeSession([_response(json_data={"id": PAGE_ID, "name": "PostHog"})])
        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session,
            mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        ):
            validate_credentials(
                page_id=PAGE_ID,
                access_token=USER_TOKEN,
                api_version=API_VERSION,
            )

        assert make_session.call_args.kwargs["capture"] is False


class TestErrorClassification:
    @pytest.mark.parametrize(
        "status_code, code, expected",
        [
            # Meta answers an expired or revoked token with HTTP 400, so only the code separates
            # auth failures from ordinary bad requests.
            (400, 190, FacebookPagesAuthError),
            (400, 102, FacebookPagesAuthError),
            (401, None, FacebookPagesAuthError),
            (400, 10, FacebookPagesPermissionError),
            (400, 200, FacebookPagesPermissionError),
            (403, None, FacebookPagesPermissionError),
            # Throttling also arrives as OAuthException — it must stay retryable.
            (400, 4, FacebookPagesRetryableError),
            (400, 17, FacebookPagesRetryableError),
            (400, 32, FacebookPagesRetryableError),
            (429, None, FacebookPagesRetryableError),
            (500, None, FacebookPagesRetryableError),
            (503, None, FacebookPagesRetryableError),
            (400, 100, FacebookPagesAPIError),
            (404, None, FacebookPagesAPIError),
        ],
    )
    def test_status_and_code_map_to_the_right_exception(
        self, status_code: int, code: int | None, expected: type[Exception]
    ) -> None:
        body = {"error": {"code": code, "message": "boom", "type": "OAuthException"}} if code else {"error": {}}
        response = _response(status_code=status_code, json_data=body)

        with pytest.raises(expected):
            raise_for_graph_error(response, mock.MagicMock())

    def test_ok_response_raises_nothing(self) -> None:
        raise_for_graph_error(_response(json_data={"data": []}), mock.MagicMock())

    @pytest.mark.parametrize(
        "exception_class, prefix",
        [(FacebookPagesAuthError, AUTH_ERROR_PREFIX), (FacebookPagesPermissionError, PERMISSION_ERROR_PREFIX)],
    )
    def test_messages_carry_the_prefix_non_retryable_errors_match_on(
        self, exception_class: type[Exception], prefix: str
    ) -> None:
        code = 190 if exception_class is FacebookPagesAuthError else 10
        response = _response(status_code=400, json_data={"error": {"code": code, "message": "boom"}})

        with pytest.raises(exception_class) as exc_info:
            raise_for_graph_error(response, mock.MagicMock())

        assert str(exc_info.value).startswith(prefix)

    @pytest.mark.parametrize("raw, expected", [("30", 30.0), ("600", 60.0), ("soon", None), (None, None)])
    def test_retry_after_header_is_honored_and_capped(self, raw: str | None, expected: float | None) -> None:
        headers = {"Retry-After": raw} if raw is not None else {}
        response = _response(status_code=429, json_data={"error": {}}, headers=headers)

        with pytest.raises(FacebookPagesRetryableError) as exc_info:
            raise_for_graph_error(response, mock.MagicMock())

        assert exc_info.value.retry_after == expected

    def test_non_json_error_body_still_classifies(self) -> None:
        response = _response(status_code=500)
        response.json.side_effect = ValueError("not json")

        with pytest.raises(FacebookPagesRetryableError):
            raise_for_graph_error(response, mock.MagicMock())


class TestTokenResolution:
    def _resolve(self, session: _FakeSession) -> str:
        return resolve_page_access_token(
            cast(requests.Session, session), API_VERSION, PAGE_ID, USER_TOKEN, mock.MagicMock()
        )

    def test_swaps_the_user_token_for_the_page_token(self) -> None:
        session = _FakeSession([_response(json_data={"id": PAGE_ID, "access_token": PAGE_TOKEN})])

        assert self._resolve(session) == PAGE_TOKEN
        assert _query(session.urls[0])["fields"] == "access_token"

    @pytest.mark.parametrize(
        "response",
        [
            _response(json_data={"id": PAGE_ID}),
            _response(status_code=400, json_data={"error": {"code": 100, "message": "nope"}}),
        ],
    )
    def test_keeps_the_user_token_when_the_page_will_not_hand_one_over(self, response: mock.MagicMock) -> None:
        # The user token can still read most edges, so let the real data request report the problem.
        assert self._resolve(_FakeSession([response])) == USER_TOKEN


class TestIntegrationToken:
    def _integration(self, kind: str = "facebook-pages", access_token: str | None = USER_TOKEN) -> mock.MagicMock:
        integration = mock.MagicMock()
        integration.kind = kind
        integration.errors = ""
        integration.access_token = access_token
        integration.config = {}
        integration.sensitive_config = {"access_token": access_token}
        return integration

    @mock.patch(f"{MODULE}.FacebookPagesIntegration.refresh_access_token")
    def test_refreshes_and_returns_the_stored_token(self, mock_refresh: mock.MagicMock) -> None:
        assert get_user_access_token(self._integration()) == USER_TOKEN
        mock_refresh.assert_called_once()

    @pytest.mark.parametrize(
        "errors, access_token",
        [(ERROR_TOKEN_REFRESH_FAILED, USER_TOKEN), ("", None)],
    )
    @mock.patch(f"{MODULE}.FacebookPagesIntegration.refresh_access_token")
    def test_a_failed_refresh_asks_the_user_to_reconnect(
        self, mock_refresh: mock.MagicMock, errors: str, access_token: str | None
    ) -> None:
        integration = self._integration(access_token=access_token)
        integration.errors = errors

        with pytest.raises(FacebookPagesTokenRefreshError):
            get_user_access_token(integration)

    def test_an_integration_of_another_kind_is_rejected(self) -> None:
        with pytest.raises(Exception, match="wrong 'kind'"):
            get_user_access_token(self._integration(kind="meta-ads"))


class TestListPages:
    def _accounts(self, ids: list[str], after: str | None) -> mock.MagicMock:
        paging: dict[str, Any] = {}
        if after:
            paging = {"cursors": {"after": after}, "next": "https://graph.facebook.com/next"}
        return _response(
            json_data={"data": [{"id": page_id, "name": f"Page {page_id}"} for page_id in ids], "paging": paging}
        )

    def _list(self, session: _FakeSession) -> list:
        return list_pages(cast(requests.Session, session), API_VERSION, USER_TOKEN, mock.MagicMock())

    def test_follows_the_after_cursor_until_paging_next_is_absent(self) -> None:
        session = _FakeSession([self._accounts(["1"], after="CUR1"), self._accounts(["2"], after=None)])

        assert [page["id"] for page in self._list(session)] == ["1", "2"]
        assert "after" not in _query(session.urls[0])
        assert _query(session.urls[1])["after"] == "CUR1"

    def test_stops_at_the_page_cap(self) -> None:
        session = _FakeSession([self._accounts([str(i)], after=f"CUR{i}") for i in range(MAX_ACCOUNT_PAGES + 5)])

        assert len(self._list(session)) == MAX_ACCOUNT_PAGES

    def test_entries_without_an_id_are_dropped(self) -> None:
        session = _FakeSession([_response(json_data={"data": [{"name": "no id"}, {"id": "1"}], "paging": {}})])

        assert [page["id"] for page in self._list(session)] == ["1"]


class TestObjectEndpoint:
    def test_page_yields_a_single_row(self) -> None:
        session = _FakeSession([_response(json_data={"id": PAGE_ID, "name": "PostHog"})])

        batches = _run("page", session, _FakeManager())

        assert batches == [[{"id": PAGE_ID, "name": "PostHog"}]]
        assert _query(session.urls[0])["fields"].startswith("id,name")


class TestEdgePagination:
    def _page(self, ids: list[str], after: str | None, created: int = NOW) -> mock.MagicMock:
        paging: dict[str, Any] = {}
        if after:
            paging = {"cursors": {"after": after}, "next": "https://graph.facebook.com/next"}
        return _response(
            json_data={
                "data": [{"id": post_id, "created_time": _iso(created)} for post_id in ids],
                "paging": paging,
            }
        )

    def test_follows_the_after_cursor_until_paging_next_is_absent(self) -> None:
        session = _FakeSession([self._page(["1", "2"], after="CUR1"), self._page(["3"], after=None)])

        batches = _run("posts", session, _FakeManager())

        assert [[row["id"] for row in batch] for batch in batches] == [["1", "2"], ["3"]]
        assert "after" not in _query(session.urls[0])
        assert _query(session.urls[1])["after"] == "CUR1"

    def test_stops_when_the_cursor_is_missing_even_though_next_is_present(self) -> None:
        session = _FakeSession(
            [_response(json_data={"data": [{"id": "1"}], "paging": {"next": "https://graph.facebook.com/next"}})]
        )

        assert _run("posts", session, _FakeManager()) == [[{"id": "1", "page_id": PAGE_ID}]]

    def test_stops_on_an_empty_page(self) -> None:
        session = _FakeSession([_response(json_data={"data": [], "paging": {"cursors": {"after": "CUR"}}})])

        assert _run("posts", session, _FakeManager()) == []

    def test_injects_the_page_id_into_every_row(self) -> None:
        session = _FakeSession([self._page(["1"], after=None)])

        batches = _run("posts", session, _FakeManager())

        assert batches[0][0]["page_id"] == PAGE_ID

    def test_state_is_saved_after_each_yielded_page(self) -> None:
        manager = _FakeManager()
        session = _FakeSession([self._page(["1"], after="CUR1"), self._page(["2"], after=None)])

        _run("posts", session, manager)

        # Only the page that had a successor is checkpointed, and it is saved after its rows
        # were yielded so a crash re-yields rather than skips them.
        assert [state.after for state in manager.saved] == ["CUR1"]

    def test_resumes_from_the_saved_cursor_and_since(self) -> None:
        manager = _FakeManager(FacebookPagesResumeConfig(after="CUR9", since=NOW - 5 * SECONDS_PER_DAY))
        session = _FakeSession([self._page(["7"], after=None)])

        _run("posts", session, manager, should_use_incremental_field=True, db_incremental_field_last_value=NOW)

        query = _query(session.urls[0])
        assert query["after"] == "CUR9"
        # The resumed window wins over the database watermark so pagination stays consistent.
        assert query["since"] == str(NOW - 5 * SECONDS_PER_DAY)


class TestEdgeIncremental:
    def _page(self, created: list[int], after: str | None) -> mock.MagicMock:
        paging: dict[str, Any] = {}
        if after:
            paging = {"cursors": {"after": after}, "next": "https://graph.facebook.com/next"}
        return _response(
            json_data={
                "data": [{"id": str(epoch), "created_time": _iso(epoch)} for epoch in created],
                "paging": paging,
            }
        )

    def test_sends_the_watermark_as_since(self) -> None:
        watermark = datetime.fromtimestamp(NOW - SECONDS_PER_DAY, UTC)
        session = _FakeSession([self._page([NOW], after=None)])

        _run(
            "posts",
            session,
            _FakeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert _query(session.urls[0])["since"] == str(NOW - SECONDS_PER_DAY)

    def test_no_since_when_incremental_is_off(self) -> None:
        session = _FakeSession([self._page([NOW], after=None)])

        _run("posts", session, _FakeManager(), should_use_incremental_field=False, db_incremental_field_last_value=NOW)

        assert "since" not in _query(session.urls[0])

    def test_stops_once_a_whole_page_predates_the_watermark(self) -> None:
        # Graph only guarantees `since` on the first request of a cursor walk; without the
        # client-side stop every incremental run would page back through all of history.
        watermark = NOW - SECONDS_PER_DAY
        session = _FakeSession(
            [
                self._page([NOW, NOW - 100], after="CUR1"),
                self._page([watermark - 1, watermark - 2], after="CUR2"),
            ]
        )

        batches = _run(
            "posts",
            session,
            _FakeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert [[row["id"] for row in batch] for batch in batches] == [[str(NOW), str(NOW - 100)]]
        assert len(session.urls) == 2

    def test_keeps_walking_when_there_is_no_watermark(self) -> None:
        session = _FakeSession(
            [
                self._page([NOW - 10 * SECONDS_PER_DAY], after="CUR1"),
                self._page([NOW - 20 * SECONDS_PER_DAY], after=None),
            ]
        )

        batches = _run("posts", session, _FakeManager())

        assert len(batches) == 2

    def test_boundary_rows_are_kept_so_merge_can_dedupe_them(self) -> None:
        watermark = NOW - SECONDS_PER_DAY
        session = _FakeSession([self._page([watermark], after=None)])

        batches = _run(
            "posts",
            session,
            _FakeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert [row["id"] for row in batches[0]] == [str(watermark)]


class TestInsights:
    def _insights(self, metric_names: Iterable[str], end_times: list[int]) -> mock.MagicMock:
        return _response(
            json_data={
                "data": [
                    {
                        "name": name,
                        "period": "day",
                        "title": name.replace("_", " "),
                        "description": "desc",
                        "values": [{"value": 7, "end_time": _iso(end)} for end in end_times],
                    }
                    for name in metric_names
                ]
            }
        )

    def test_flatten_produces_a_row_per_metric_and_point(self) -> None:
        payload = {
            "data": [
                {
                    "name": "page_impressions",
                    "period": "day",
                    "values": [{"value": 3, "end_time": "2024-01-01T08:00:00+0000"}],
                },
                {
                    "name": "page_fans",
                    "period": "day",
                    "values": [{"value": 5, "end_time": "2024-01-01T08:00:00+0000"}],
                },
            ]
        }

        rows = flatten_insights(payload, PAGE_ID)

        assert [(row["name"], row["value"], row["page_id"]) for row in rows] == [
            ("page_impressions", 3.0, PAGE_ID),
            ("page_fans", 5.0, PAGE_ID),
        ]

    def test_breakdown_values_go_to_value_json(self) -> None:
        payload = {
            "data": [
                {
                    "name": "page_impressions_by_country",
                    "period": "day",
                    "values": [{"value": {"GB": 4}, "end_time": "2024-01-01T08:00:00+0000"}],
                }
            ]
        }

        rows = flatten_insights(payload, PAGE_ID)

        assert rows[0]["value"] is None
        assert rows[0]["value_json"] == '{"GB": 4}'

    @pytest.mark.parametrize(
        "payload",
        [
            {"data": [{"name": "page_fans", "period": "day", "values": [{"value": 1}]}]},
            {"data": [{"name": "page_fans", "period": "day", "values": []}]},
            {"data": []},
            {},
        ],
    )
    def test_points_without_an_end_time_are_dropped(self, payload: dict[str, Any]) -> None:
        # end_time is part of the primary key, so a point without one can't be merged safely.
        assert flatten_insights(payload, PAGE_ID) == []

    def test_first_sync_walks_the_lookback_in_windows_meta_accepts(self) -> None:
        expected_windows = -(-DEFAULT_INSIGHTS_LOOKBACK_DAYS // INSIGHTS_WINDOW_DAYS)
        session = _FakeSession([self._insights(["page_fans"], [NOW]) for _ in range(expected_windows)])

        _run("page_insights", session, _FakeManager())

        assert len(session.urls) == expected_windows
        for url in session.urls:
            query = _query(url)
            width = int(query["until"]) - int(query["since"])
            assert 0 < width <= INSIGHTS_WINDOW_DAYS * SECONDS_PER_DAY
            assert query["period"] == "day"

    def test_windows_are_contiguous_and_ascending(self) -> None:
        expected_windows = -(-DEFAULT_INSIGHTS_LOOKBACK_DAYS // INSIGHTS_WINDOW_DAYS)
        session = _FakeSession([self._insights(["page_fans"], [NOW]) for _ in range(expected_windows)])

        _run("page_insights", session, _FakeManager())

        bounds = [(int(_query(url)["since"]), int(_query(url)["until"])) for url in session.urls]
        assert all(bounds[i][1] == bounds[i + 1][0] for i in range(len(bounds) - 1))
        assert bounds[-1][1] == NOW

    def test_incremental_starts_from_the_watermark(self) -> None:
        watermark = datetime.fromtimestamp(NOW - 10 * SECONDS_PER_DAY, UTC)
        session = _FakeSession([self._insights(["page_fans"], [NOW])])

        _run(
            "page_insights",
            session,
            _FakeManager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )

        assert len(session.urls) == 1
        assert int(_query(session.urls[0])["since"]) == NOW - 10 * SECONDS_PER_DAY

    def test_resumes_from_the_saved_window(self) -> None:
        manager = _FakeManager(FacebookPagesResumeConfig(window_since=NOW - 5 * SECONDS_PER_DAY, range_until=NOW))
        session = _FakeSession([self._insights(["page_fans"], [NOW])])

        _run("page_insights", session, manager)

        assert int(_query(session.urls[0])["since"]) == NOW - 5 * SECONDS_PER_DAY

    def test_state_is_saved_between_windows(self) -> None:
        manager = _FakeManager(FacebookPagesResumeConfig(window_since=NOW - 100 * SECONDS_PER_DAY, range_until=NOW))
        session = _FakeSession([self._insights(["page_fans"], [NOW]), self._insights(["page_fans"], [NOW])])

        _run("page_insights", session, manager)

        assert len(session.urls) == 2
        assert [state.window_since for state in manager.saved] == [NOW - 10 * SECONDS_PER_DAY]

    @pytest.mark.parametrize(
        "message, expected",
        [
            ("(#100) page_fans is no longer available", ["page_fans"]),
            ("(#100) metric[0] must be one of page_impressions_unique", ["page_impressions_unique"]),
            ("(#100) nothing familiar here", []),
        ],
    )
    def test_unsupported_metrics_matches_whole_names_only(self, message: str, expected: list[str]) -> None:
        # `page_impressions` is a prefix of `page_impressions_unique`; a substring test would
        # drop metrics Meta never complained about.
        assert unsupported_metrics(message, list(PAGE_INSIGHTS_METRICS)) == expected

    def test_rejected_metrics_are_dropped_and_the_window_is_retried(self) -> None:
        session = _FakeSession(
            [
                _response(
                    status_code=400,
                    json_data={"error": {"code": 100, "message": "(#100) page_fans is no longer available"}},
                ),
                self._insights(["page_impressions"], [NOW]),
            ]
        )
        manager = _FakeManager(FacebookPagesResumeConfig(window_since=NOW - SECONDS_PER_DAY, range_until=NOW))

        batches = _run("page_insights", session, manager)

        assert "page_fans" in _query(session.urls[0])["metric"]
        assert "page_fans" not in _query(session.urls[1])["metric"]
        assert [row["name"] for row in batches[0]] == ["page_impressions"]

    def test_an_unrelated_api_error_is_not_swallowed(self) -> None:
        session = _FakeSession(
            [_response(status_code=400, json_data={"error": {"code": 100, "message": "(#100) bad since value"}})]
        )
        manager = _FakeManager(FacebookPagesResumeConfig(window_since=NOW - SECONDS_PER_DAY, range_until=NOW))

        with pytest.raises(FacebookPagesAPIError):
            _run("page_insights", session, manager)


class TestValidateCredentials:
    def _validate(
        self, session: _FakeSession, schema_name: Optional[str] = None, page_id: str = PAGE_ID
    ) -> tuple[bool, str | None]:
        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        ):
            return validate_credentials(
                page_id=page_id,
                access_token=USER_TOKEN,
                api_version=API_VERSION,
                schema_name=schema_name,
            )

    def test_blank_page_id_fails_without_a_request(self) -> None:
        ok, error = self._validate(_FakeSession([]), page_id="   ")

        assert ok is False
        assert error is not None

    def test_probes_the_page_node_at_source_create(self) -> None:
        session = _FakeSession([_response(json_data={"id": PAGE_ID, "name": "PostHog"})])

        assert self._validate(session) == (True, None)
        assert session.urls[0].startswith(f"https://graph.facebook.com/{API_VERSION}/{PAGE_ID}?")

    @pytest.mark.parametrize(
        "schema_name, expected_path",
        [
            ("posts", f"{PAGE_ID}/posts"),
            ("videos", f"{PAGE_ID}/videos"),
            ("page_insights", f"{PAGE_ID}/insights"),
            ("page", PAGE_ID),
        ],
    )
    def test_scoped_probe_hits_the_endpoint_being_synced(self, schema_name: str, expected_path: str) -> None:
        session = _FakeSession([_response(json_data={"data": []})])

        assert self._validate(session, schema_name=schema_name) == (True, None)
        assert urlparse(session.urls[0]).path == f"/{API_VERSION}/{expected_path}"

    @pytest.mark.parametrize(
        "status_code, code",
        [(400, 190), (401, None), (400, 10), (403, None), (400, 100)],
    )
    def test_api_failures_are_reported_rather_than_raised(self, status_code: int, code: int | None) -> None:
        session = _FakeSession(
            [_response(status_code=status_code, json_data={"error": {"code": code, "message": "boom"}})]
        )

        ok, error = self._validate(session)

        assert ok is False
        assert error

    def test_network_failures_are_reported(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = requests.ConnectionError("no route to host")

        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        ):
            ok, error = validate_credentials(
                page_id=PAGE_ID,
                access_token=USER_TOKEN,
                api_version=API_VERSION,
            )

        assert ok is False
        assert "no route to host" in (error or "")


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(FACEBOOK_PAGES_ENDPOINTS))
    def test_response_matches_the_endpoint_settings(self, endpoint: str) -> None:
        config = FACEBOOK_PAGES_ENDPOINTS[endpoint]

        response = facebook_pages_source(
            page_id=PAGE_ID,
            access_token=USER_TOKEN,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == config.sort_mode
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)
        assert response.partition_mode == ("datetime" if config.partition_key else None)

    @pytest.mark.parametrize("endpoint", ["posts", "videos"])
    def test_edges_are_descending_because_graph_returns_newest_first(self, endpoint: str) -> None:
        response = facebook_pages_source(
            page_id=PAGE_ID,
            access_token=USER_TOKEN,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeManager(),
        )

        assert response.sort_mode == "desc"

    def test_items_is_lazy(self) -> None:
        response = facebook_pages_source(
            page_id=PAGE_ID,
            access_token=USER_TOKEN,
            endpoint="page",
            logger=mock.MagicMock(),
            resumable_source_manager=_FakeManager(),
        )
        session = _FakeSession([_response(json_data={"id": PAGE_ID})])

        with (
            mock.patch(f"{MODULE}.make_tracked_session", return_value=session),
            mock.patch(f"{MODULE}.resolve_page_access_token", return_value=PAGE_TOKEN),
        ):
            items = cast(Iterator[Any], response.items())
            assert list(items) == [[{"id": PAGE_ID}]]


class TestTimestampCoercion:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (NOW, NOW),
            (float(NOW), NOW),
            (str(NOW), NOW),
            ("2023-11-14T22:13:20+0000", NOW),
            ("2023-11-14T22:13:20Z", NOW),
            (datetime.fromtimestamp(NOW, UTC), NOW),
            (datetime.fromtimestamp(NOW, UTC).replace(tzinfo=None), NOW),
        ],
    )
    def test_accepts_the_shapes_a_watermark_arrives_in(self, value: Any, expected: int) -> None:
        assert _to_epoch_seconds(value) == expected

    @pytest.mark.parametrize("value", [None, "", "  ", True, object()])
    def test_rejects_values_that_are_not_timestamps(self, value: Any) -> None:
        with pytest.raises(ValueError):
            _to_epoch_seconds(value)


APP_SECRET = "meta-app-secret"


def _expected_proof(token: str) -> str:
    return hmac.new(APP_SECRET.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


class TestAppSecretProof:
    """Meta verifies `appsecret_proof` alongside the token, so a token lifted out of PostHog
    can't be replayed against Graph without the app secret too."""

    def test_user_token_requests_are_signed(self) -> None:
        session = _FakeSession([_response(json_data={"data": [{"id": PAGE_ID, "name": "PostHog"}], "paging": {}})])

        with mock.patch(f"{MODULE}._meta_app_secret", return_value=APP_SECRET):
            list_pages(cast(Any, session), API_VERSION, USER_TOKEN, mock.MagicMock())

        assert _query(session.urls[0])["appsecret_proof"] == _expected_proof(USER_TOKEN)

    def test_page_token_requests_are_signed_with_the_page_token(self) -> None:
        session = _FakeSession([_response(json_data={"data": [], "paging": {}})])

        with mock.patch(f"{MODULE}._meta_app_secret", return_value=APP_SECRET):
            _run("posts", session, _FakeManager())

        # The proof is keyed by the app secret but derived from whichever token signs the
        # request, so the Page token needs its own proof rather than the user token's.
        assert _query(session.urls[0])["appsecret_proof"] == _expected_proof(PAGE_TOKEN)
        assert _query(session.urls[0])["appsecret_proof"] != _expected_proof(USER_TOKEN)

    def test_the_proof_is_derived_from_the_oauth_app_secret(self) -> None:
        config = mock.MagicMock()
        config.client_secret = APP_SECRET

        with mock.patch(f"{MODULE}.OauthIntegration.oauth_config_for_kind", return_value=config) as for_kind:
            assert appsecret_proof(USER_TOKEN) == _expected_proof(USER_TOKEN)

        assert for_kind.call_args.args == (INTEGRATION_KIND,)

    def test_no_proof_is_sent_when_the_meta_app_is_not_configured(self) -> None:
        session = _FakeSession([_response(json_data={"data": [], "paging": {}})])

        with mock.patch(
            f"{MODULE}.OauthIntegration.oauth_config_for_kind",
            side_effect=NotImplementedError("Facebook Pages app not configured"),
        ):
            assert appsecret_proof(USER_TOKEN) is None
            _run("posts", session, _FakeManager())

        assert "appsecret_proof" not in _query(session.urls[0])

    def test_the_proof_never_reaches_a_log_or_sample(self) -> None:
        # `scrub_url` is what the tracked transport logs, so the denylist has to name the param.
        proof = _expected_proof(USER_TOKEN)
        scrubbed = scrub_url(f"https://graph.facebook.com/{API_VERSION}/{PAGE_ID}?appsecret_proof={proof}")

        assert proof not in scrubbed


class TestPageIdValidation:
    """`page_id` is interpolated into the Graph path, so anything but a bare node ID could
    redirect the request at another endpoint (e.g. `/me/accounts?fields=access_token`) and have
    the response written into the warehouse."""

    INJECTIONS = [
        "me/accounts?fields=access_token&x=",
        "me/accounts%3Ffields=access_token",
        f"{PAGE_ID}/../me/accounts",
        f"{PAGE_ID}?fields=access_token",
        f"{PAGE_ID}&fields=access_token",
        "me",
        "",
        "   ",
    ]

    @pytest.mark.parametrize("page_id", INJECTIONS)
    def test_validate_credentials_rejects_without_making_a_request(self, page_id: str) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            is_valid, error = validate_credentials(
                page_id=page_id,
                access_token=USER_TOKEN,
                api_version=API_VERSION,
            )

        assert is_valid is False
        assert error is not None
        make_session.assert_not_called()

    @pytest.mark.parametrize("page_id", INJECTIONS)
    def test_the_pipeline_path_rejects_without_making_a_request(self, page_id: str) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            with pytest.raises(FacebookPagesInvalidPageIdError):
                facebook_pages_source(
                    page_id=page_id,
                    access_token=USER_TOKEN,
                    endpoint="page",
                    logger=mock.MagicMock(),
                    resumable_source_manager=_FakeManager(),
                    api_version=API_VERSION,
                )

        make_session.assert_not_called()

    @pytest.mark.parametrize("page_id", INJECTIONS)
    def test_get_rows_rejects_a_config_persisted_before_the_check_existed(self, page_id: str) -> None:
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            with pytest.raises(FacebookPagesInvalidPageIdError):
                list(
                    get_rows(
                        page_id=page_id,
                        access_token=USER_TOKEN,
                        endpoint="page",
                        api_version=API_VERSION,
                        logger=mock.MagicMock(),
                        resumable_source_manager=_FakeManager(),
                    )
                )

        make_session.assert_not_called()

    def test_a_numeric_page_id_is_accepted(self) -> None:
        assert validated_page_id(f"  {PAGE_ID} ") == PAGE_ID
