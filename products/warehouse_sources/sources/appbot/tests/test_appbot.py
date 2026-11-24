from datetime import UTC, date, datetime
from typing import Any

import pytest
import time_machine
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.appbot import appbot
from products.warehouse_sources.sources.appbot._config import AppbotSourceConfig
from products.warehouse_sources.sources.appbot.appbot import (
    AppbotIncompleteReadError,
    AppbotPageTokenExpiredError,
    AppbotResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.sources.appbot.source import AppbotSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _frozen_clock():
    with time_machine.travel(NOW, tick=False):
        yield


def _driver() -> SourceDriver:
    return SourceDriver(AppbotSource(), AppbotSourceConfig(api_username="user", api_password="secret"))


def _apps(*app_ids: int) -> ScriptedResponse:
    return ScriptedResponse(json={"results": [{"id": app_id, "name": f"App {app_id}"} for app_id in app_ids]})


def _reviews(ids: list[int], page: int, total_pages: int, total_count: int | None = None) -> ScriptedResponse:
    return ScriptedResponse(
        json={
            "results": [{"id": review_id, "app_id": ":app_id", "rating": 5} for review_id in ids],
            "count": len(ids),
            "page": page,
            "total_pages": total_pages,
            "total_count": len(ids) if total_count is None else total_count,
        }
    )


def _ratings(rows: list[dict[str, Any]], token: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={"count": len(rows), "next_page_token": token, "results": rows})


class TestReviews:
    @parameterized.expand(
        [
            ("full_refresh", False, None, "2008-01-01"),
            # The lookback reads the last week again, because reviews reach Appbot late.
            ("incremental", True, date(2026, 3, 1), "2026-02-22"),
        ]
    )
    def test_walks_every_page_of_every_app(
        self, _name: str, incremental: bool, last_value: date | None, expected_start: str
    ) -> None:
        result = _driver().run(
            "reviews",
            [
                _apps(1, 2),
                _reviews([10, 11], page=1, total_pages=2),
                _reviews([12], page=2, total_pages=2),
                _reviews([20], page=1, total_pages=1),
            ],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.paths[1:] == ["/api/v2/apps/1/reviews"] * 2 + ["/api/v2/apps/2/reviews"]
        assert [(row["app_id"], row["id"]) for row in result.rows] == [(1, 10), (1, 11), (1, 12), (2, 20)]
        assert result.params("page")[1:] == ["1", "2", "1"]
        assert set(result.params("start")[1:]) == {expected_start}
        assert set(result.params("end")[1:]) == {"2026-03-10"}
        assert result.requests[0].headers["authorization"].startswith("Basic ")

    def test_splits_a_window_that_holds_more_reviews_than_appbot_can_page(self) -> None:
        result = _driver().run(
            "reviews",
            [
                _apps(1),
                _reviews([1], page=1, total_pages=3000, total_count=60_000),
                _reviews([2], page=1, total_pages=1),
                _reviews([3], page=1, total_pages=1),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [2, 3]
        windows = list(zip(result.params("start")[1:], result.params("end")[1:]))
        assert windows == [
            ("2008-01-01", "2026-03-10"),
            ("2008-01-01", "2017-02-03"),
            ("2017-02-04", "2026-03-10"),
        ]

    def test_resumes_inside_the_saved_window_and_page(self) -> None:
        # The app list comes back in another order, so a resume must not depend on list positions.
        result = _driver().run(
            "reviews",
            [_apps(3, 1, 2), _reviews([7], page=4, total_pages=4), _reviews([8], page=1, total_pages=1)],
            resume_state=AppbotResumeConfig(done_app_ids=[1], app_id=2, windows=[["2020-01-01", "2026-03-10"]], page=4),
        )

        assert result.raised is None
        assert result.paths == ["/api/v2/apps", "/api/v2/apps/2/reviews", "/api/v2/apps/3/reviews"]
        assert result.params("page")[1:] == ["4", "1"]
        assert result.params("start")[1:] == ["2020-01-01", "2008-01-01"]
        assert [(row["app_id"], row["id"]) for row in result.rows] == [(2, 7), (3, 8)]

    @parameterized.expand(
        [
            (
                "one_day_over_the_page_depth_limit",
                [["2026-03-10", "2026-03-10"]],
                [_reviews([1], page=1, total_pages=3000, total_count=60_000)],
            ),
            (
                "page_cap_reached",
                [["2026-01-01", "2026-03-10"]],
                [_reviews([1], page=1, total_pages=9), _reviews([2], page=2, total_pages=9)],
            ),
        ]
    )
    def test_fails_instead_of_skipping_reviews_it_cannot_read(
        self, _name: str, windows: list[list[str]], pages: list[ScriptedResponse]
    ) -> None:
        with mock.patch.object(appbot, "MAX_REVIEW_PAGES_PER_WINDOW", 2):
            result = _driver().run(
                "reviews",
                [_apps(1), *pages],
                resume_state=AppbotResumeConfig(app_id=1, windows=windows, page=1),
            )

        assert isinstance(result.raised, AppbotIncompleteReadError)
        # The cursor stays on the unread window, so no later state claims the window is done.
        assert result.final_state.windows == windows

    def test_skips_an_app_removed_after_the_app_list_was_read(self) -> None:
        result = _driver().run(
            "reviews",
            [_apps(1, 2), ScriptedResponse(status=404, json={"errors": ["Not found"]}), _reviews([5], 1, 1)],
        )

        assert result.raised is None
        assert [(row["app_id"], row["id"]) for row in result.rows] == [(2, 5)]


class TestRatings:
    @parameterized.expand(
        [
            ("full_refresh", False, None, "2008-01-01T00:00:00Z"),
            ("incremental", True, datetime(2026, 3, 5, 6, 30, tzinfo=UTC), "2026-03-03T06:30:00Z"),
        ]
    )
    def test_follows_page_tokens_and_keys_country_summaries(
        self, _name: str, incremental: bool, last_value: datetime | None, expected_start: str
    ) -> None:
        uk = {"country_id": 7, "country_code": "UK", "created_at": "2026-03-01T01:00:00.000Z", "total": 10}
        summary = {"country_id": None, "country": None, "created_at": "2026-03-01T01:00:00.000Z", "total": 99}
        result = _driver().run(
            "ratings",
            [_apps(1), _ratings([uk], token="tok-1"), _ratings([summary], token=None)],
            should_use_incremental_field=incremental,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [
            "1:7:2026-03-01T01:00:00.000Z",
            "1:all:2026-03-01T01:00:00.000Z",
        ]
        assert result.params("next_page_token")[1:] == [None, "tok-1"]
        # Appbot requires every later page to repeat the query of the first page.
        assert set(result.params("start")[1:]) == {expected_start}
        assert set(result.params("page_size")[1:]) == {"1000"}

    @parameterized.expand(
        [
            ("saved_token_refused", AppbotResumeConfig(app_id=1, next_page_token="expired"), [], 400),
            ("saved_token_for_a_removed_app", AppbotResumeConfig(app_id=1, next_page_token="expired"), [], 404),
            ("token_expired_during_the_walk", None, [_ratings([{"country_id": 7, "created_at": "t1"}], "tok-1")], 400),
        ]
    )
    def test_restarts_the_sync_when_a_page_token_is_refused(
        self, _name: str, resume_state: AppbotResumeConfig | None, pages: list[ScriptedResponse], status: int
    ) -> None:
        result = _driver().run(
            "ratings",
            [_apps(1, 2), *pages, ScriptedResponse(status=status, json={"errors": ["invalid token"]})],
            resume_state=resume_state,
        )

        # Reading the app again would append its earlier pages twice, so the run drops its cursor and
        # the retried attempt reads the table from the start.
        assert isinstance(result.raised, AppbotPageTokenExpiredError)
        assert result.final_state is None
        assert "/api/v2/apps/2/ratings/bulk" not in result.paths


def test_bad_credentials_fail_with_a_non_retryable_error() -> None:
    result = _driver().run("reviews", [ScriptedResponse(status=401, json={"error": "V2 API credentials are invalid"})])

    assert isinstance(result.raised, requests.HTTPError)
    message = str(result.raised)
    assert "secret" not in message
    assert any(key in message for key in AppbotSource().get_non_retryable_errors())


@parameterized.expand(
    [
        ("valid", 200, True, None),
        ("bad_credentials", 401, False, "didn't accept"),
        ("unexpected_status", 404, False, "unexpected status code (404)"),
    ]
)
def test_validate_credentials(_name: str, status: int, expected_ok: bool, expected_message: str | None) -> None:
    with scripted_network([ScriptedResponse(status=status, json={})]) as network:
        ok, message = validate_credentials("user", "secret")

    assert ok is expected_ok
    if expected_message is None:
        assert message is None
    else:
        assert message is not None and expected_message in message
    assert network.requests_log[0].path == "/api/v2/me"
