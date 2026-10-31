from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.fake_network import RecordedRequest
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pylon import PylonSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon import pylon
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.pylon import (
    PYLON_EU_BASE_URL,
    PYLON_US_BASE_URL,
    PylonResumeConfig,
    _format_rfc3339,
    _to_datetime,
    base_url_for_token,
    get_rows,
    pylon_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.settings import PYLON_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.pylon.source import PylonSource


def _page(items: list[dict[str, Any]], cursor: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"data": items, "request_id": "req"}
    if cursor is not None:
        body["pagination"] = {"cursor": cursor, "has_next_page": True}
    else:
        body["pagination"] = {"cursor": "", "has_next_page": False}
    return body


def _no_resume_manager() -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = False
    manager.load_state.return_value = None
    return manager


class TestFormatRfc3339:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_rfc3339(value) == expected


class TestToDatetime:
    @parameterized.expand(
        [
            ("aware_datetime", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("naive_datetime", datetime(2026, 1, 2, 3, 4, 5), datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("date", date(2026, 1, 2), datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)),
            ("rfc3339_string", "2026-01-02T03:04:05Z", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)),
        ]
    )
    def test_to_datetime(self, _name: str, value: Any, expected: datetime) -> None:
        assert _to_datetime(value) == expected


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("eu_token", "pylon_api_eu_abc123", f"{PYLON_EU_BASE_URL}/me"),
            ("us_token", "pylon_api_abc123", f"{PYLON_US_BASE_URL}/me"),
            ("unprefixed_token", "token", f"{PYLON_US_BASE_URL}/me"),
        ]
    )
    def test_validate_credentials_hits_me_endpoint(self, _name: str, api_token: str, expected_url: str) -> None:
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200)
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: session)
            pylon.validate_credentials(api_token)
        called_url = session.get.call_args.args[0]
        assert called_url == expected_url


class TestBaseUrlForToken:
    @parameterized.expand(
        [
            ("eu_prefix", "pylon_api_eu_abc123", PYLON_EU_BASE_URL),
            ("us_prefix", "pylon_api_abc123", PYLON_US_BASE_URL),
            ("unprefixed", "token", PYLON_US_BASE_URL),
            # "eu" only routes as the documented prefix, not anywhere in the token.
            ("eu_elsewhere", "pylon_api_zeu_abc", PYLON_US_BASE_URL),
        ]
    )
    def test_routes_by_prefix(self, _name: str, api_token: str, expected: str) -> None:
        assert base_url_for_token(api_token) == expected


class TestSyncPathRegion:
    @parameterized.expand(
        [
            ("eu_token", "pylon_api_eu_abc123", PYLON_EU_BASE_URL),
            ("us_token", "pylon_api_abc123", PYLON_US_BASE_URL),
        ]
    )
    def test_get_rows_requests_the_tokens_region(self, _name: str, api_token: str, expected_base: str) -> None:
        fetch_page = MagicMock(return_value=_page([{"id": "1"}]))
        manager = _no_resume_manager()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch_page)
            list(get_rows(api_token=api_token, endpoint="teams", logger=MagicMock(), resumable_source_manager=manager))

        requested_url = fetch_page.call_args.args[1]
        assert requested_url.startswith(expected_base)


class TestSimpleEndpointPagination:
    def test_stops_when_cursor_does_not_advance(self) -> None:
        # An endpoint that keeps returning the same cursor with has_next_page=true must not loop forever.
        stuck = _page([{"id": "1"}], cursor="same")
        manager = _no_resume_manager()

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", MagicMock(return_value=stuck))
            batches = list(
                get_rows(api_token="t", endpoint="teams", logger=MagicMock(), resumable_source_manager=manager)
            )

        # First page yielded, second fetch returns the same cursor -> stop. So at most two pages.
        assert len(batches) <= 2

    def test_accounts_sends_required_limit(self) -> None:
        manager = _no_resume_manager()
        fetch = MagicMock(side_effect=[_page([{"id": "1"}])])

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(get_rows(api_token="t", endpoint="accounts", logger=MagicMock(), resumable_source_manager=manager))

        url = fetch.call_args_list[0].args[1]
        assert parse_qs(urlparse(url).query)["limit"] == ["999"]


class TestFanOutEndpoint:
    def test_resumes_from_saved_object_type(self) -> None:
        object_types = PYLON_ENDPOINTS["custom_fields"].fan_out_object_types or []
        resume_type = object_types[2]
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PylonResumeConfig(object_type=resume_type)
        # Remaining object types after (and including) the resume position.
        remaining = object_types[object_types.index(resume_type) :]
        fetch = MagicMock(side_effect=[_page([{"id": "x", "object_type": ot}]) for ot in remaining])

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            batches = list(
                get_rows(api_token="t", endpoint="custom_fields", logger=MagicMock(), resumable_source_manager=manager)
            )

        seen = [row["object_type"] for batch in batches for row in batch]
        assert seen == remaining


class TestWindowedIssues:
    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_first_sync_walks_lookback_in_30_day_windows(self) -> None:
        manager = _no_resume_manager()
        fetch = MagicMock(return_value=_page([{"id": "i", "created_at": "2026-01-01T00:00:00Z"}]))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(
                get_rows(
                    api_token="t",
                    endpoint="issues",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=None,
                )
            )

        windows = [parse_qs(urlparse(c.args[1]).query) for c in fetch.call_args_list]
        # 365-day lookback in <=30-day windows => 13 windows.
        assert len(windows) == 13
        # First window starts a year before frozen now and the last window ends exactly at now.
        assert windows[0]["start_time"] == ["2025-06-23T00:00:00Z"]
        assert windows[-1]["end_time"] == ["2026-06-23T00:00:00Z"]
        # Each window is contiguous: a window's end is the next window's start.
        for earlier, later in zip(windows, windows[1:]):
            assert earlier["end_time"] == later["start_time"]

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_resumes_from_saved_window(self) -> None:
        manager = MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = PylonResumeConfig(cursor="page2", window_start="2026-06-10T00:00:00Z")
        fetch = MagicMock(return_value=_page([{"id": "i", "created_at": "2026-06-11T00:00:00Z"}]))

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(pylon, "make_tracked_session", lambda *a, **k: MagicMock())
            mp.setattr(pylon, "_fetch_page", fetch)
            list(
                get_rows(
                    api_token="t",
                    endpoint="issues",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2020, 1, 1, tzinfo=UTC),
                )
            )

        first = parse_qs(urlparse(fetch.call_args_list[0].args[1]).query)
        # Resume picks up at the saved window start and saved cursor, not the stale watermark.
        assert first["start_time"] == ["2026-06-10T00:00:00Z"]
        assert first["cursor"] == ["page2"]


class TestPylonSourceResponse:
    @parameterized.expand(
        [
            ("issues", ["id"], "created_at"),
            ("accounts", ["id"], "created_at"),
            ("contacts", ["id"], None),
            ("custom_fields", ["object_type", "id"], None),
            ("issue_statuses", ["slug"], None),
            ("tasks", ["id"], "created_at"),
        ]
    )
    def test_source_response_shape(self, endpoint: str, primary_keys: list[str], partition_key: str | None) -> None:
        response = pylon_source(
            api_token="t", endpoint=endpoint, logger=MagicMock(), resumable_source_manager=_no_resume_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == "asc"
        if partition_key is None:
            assert response.partition_keys is None
            assert response.partition_mode is None
        else:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
            assert response.partition_format == "month"


def _driver() -> SourceDriver:
    return SourceDriver(PylonSource(), PylonSourceConfig(api_token="pylon_api_token"))


def _scripted_page(items: list[dict[str, Any]], cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json=_page(items, cursor))


class TestChildEndpoints:
    @parameterized.expand(
        [
            ("incremental", True, "2026-01-02T03:04:05Z", "2026-01-02T03:04:05Z"),
            ("full_refresh", False, None, None),
        ]
    )
    def test_survey_responses_walk_every_survey_to_its_last_page(
        self, _name: str, should_use_incremental_field: bool, last_value: str | None, expected_filter: str | None
    ) -> None:
        result = _driver().run(
            "survey_responses",
            route(
                {
                    "/surveys": [ScriptedResponse(json={"data": [{"id": "s1"}, {"id": "s2"}], "request_id": "r"})],
                    "/surveys/s1/responses": [
                        _scripted_page([{"id": "r1"}], cursor="c2"),
                        _scripted_page([{"id": "r2", "survey_id": "s1"}]),
                    ],
                    "/surveys/s2/responses": [_scripted_page([{"id": "r3"}])],
                }
            ),
            incremental_field="submitted_at",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.paths == ["/surveys", "/surveys/s1/responses", "/surveys/s1/responses", "/surveys/s2/responses"]
        assert result.params("cursor") == [None, None, "c2", None]
        assert result.params("submitted_after")[1:] == [expected_filter] * 3
        assert [(row["survey_id"], row["id"]) for row in result.rows] == [("s1", "r1"), ("s1", "r2"), ("s2", "r3")]
        # One request series per survey, so rows are not ordered across the table.
        assert result.response is not None
        assert result.response.sort_mode is None

    @parameterized.expand(
        [
            (
                "mid_parent",
                False,
                ["/knowledge-bases", "/knowledge-bases/kb2/articles", "/knowledge-bases/kb3/articles"],
                ["c2", None],
            ),
            ("parent_completed", True, ["/knowledge-bases", "/knowledge-bases/kb3/articles"], [None]),
        ]
    )
    def test_articles_resume_at_the_saved_knowledge_base(
        self, _name: str, parent_completed: bool, expected_paths: list[str], expected_cursors: list[str | None]
    ) -> None:
        result = _driver().run(
            "knowledge_base_articles",
            route(
                {
                    "/knowledge-bases": [_scripted_page([{"id": "kb1"}, {"id": "kb2"}, {"id": "kb3"}])],
                    "/knowledge-bases/kb2/articles": [_scripted_page([{"id": "a2"}])],
                    "/knowledge-bases/kb3/articles": [_scripted_page([{"id": "a3"}])],
                }
            ),
            resume_state=PylonResumeConfig(cursor="c2", parent_id="kb2", parent_completed=parent_completed),
        )

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("cursor")[1:] == expected_cursors
        assert all(row["knowledge_base_id"] in {"kb2", "kb3"} for row in result.rows)

    @time_machine.travel("2026-06-23T00:00:00Z", tick=False)
    def test_issue_messages_fan_out_over_every_issues_window(self) -> None:
        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/issues":
                if request.param("start_time") == "2026-06-18T00:00:00Z":
                    return _scripted_page([{"id": "i1"}])
                return _scripted_page([])
            assert request.path == "/issues/i1/messages"
            return _scripted_page([{"id": "m1"}, {"id": "m2"}])

        result = _driver().run("issue_messages", respond)

        assert result.raised is None
        issue_requests = [request for request in result.requests if request.path == "/issues"]
        assert len(issue_requests) == 13
        assert issue_requests[0].param("start_time") == "2025-06-23T00:00:00Z"
        assert issue_requests[-1].param("end_time") == "2026-06-23T00:00:00Z"
        assert [(row["issue_id"], row["id"]) for row in result.rows] == [("i1", "m1"), ("i1", "m2")]
