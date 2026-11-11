import base64
from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
import time_machine
from unittest.mock import MagicMock

from parameterized import parameterized

from products.warehouse_sources.sources.blueshift._config import BlueshiftSourceConfig
from products.warehouse_sources.sources.blueshift.blueshift import (
    MAX_STATS_RETRY_ATTEMPTS,
    MAX_STATS_RETRY_WAIT_SECONDS,
    BlueshiftResumeConfig,
    BlueshiftRetryableError,
    BlueshiftStatsCursor,
    _wait_stats,
)
from products.warehouse_sources.sources.blueshift.source import BlueshiftSource
from products.warehouse_sources.sources.sdk import SourceCursorManager
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network

API_KEY = "test-user-api-key"
AUTH_VALUE = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def _driver(region: Literal["us", "eu"] = "us") -> SourceDriver:
    return SourceDriver(BlueshiftSource(), BlueshiftSourceConfig(api_key=API_KEY, region=region))


def _no_stored_cursor() -> SourceCursorManager[BlueshiftStatsCursor]:
    return SourceCursorManager(BlueshiftStatsCursor, None, BlueshiftSource())


def _campaign(uuid: str) -> dict[str, Any]:
    return {"uuid": uuid, "name": f"Campaign {uuid}", "statistics": {"sends": 10, "opens": 4}}


def _segments(start: int, stop: int) -> ScriptedResponse:
    return ScriptedResponse(json={"segments": [{"uuid": f"s{i}"} for i in range(start, stop)]})


class TestBlueshiftLists:
    @parameterized.expand(
        [
            ("pages_count_from_zero", [_segments(0, 100), _segments(100, 101)], ["0", "1"], 101),
            ("pages_count_from_one", [_segments(0, 100), _segments(0, 100), _segments(100, 150)], ["0", "1", "2"], 150),
            ("page_param_ignored", always(_segments(0, 100)), ["0", "1", "2"], 100),
        ]
    )
    def test_page_walk_ends_without_an_empty_page(
        self, _name: str, script: Any, pages: list[str], row_count: int
    ) -> None:
        result = _driver().run("segments", script)

        assert result.raised is None
        assert result.params("page") == pages
        assert set(result.params("per_page")) == {"100"}
        assert {r.headers.get("authorization") for r in result.requests} == {AUTH_VALUE}
        assert len(result.rows) == row_count
        assert len({row["uuid"] for row in result.rows}) == row_count
        assert result.saved_states[-1] == BlueshiftResumeConfig(next_page=len(pages))

    @parameterized.expand(
        [
            ("both_passes", None, True, ["false", "true"], ["a", "b", "c"]),
            ("resume_in_archived_pass", BlueshiftResumeConfig(next_page=0, list_pass=1), True, ["true"], ["b", "c"]),
            ("rows_without_archived_flag", None, False, ["false", "true"], ["a", "b", "c"]),
        ]
    )
    def test_campaigns_writes_each_campaign_in_one_pass(
        self,
        _name: str,
        resume_state: BlueshiftResumeConfig | None,
        with_flag: bool,
        archived: list[str],
        uuids: list[str],
    ) -> None:
        def answer(request: Any) -> ScriptedResponse:
            rows = [("a", False), ("b", True)] if request.param("archived") == "false" else [("b", True), ("c", True)]
            return ScriptedResponse(
                json=[{"uuid": uuid, **({"archived": flag} if with_flag else {})} for uuid, flag in rows]
            )

        result = _driver().run("campaigns", answer, resume_state=resume_state)

        assert result.raised is None
        assert result.params("archived") == archived
        assert set(result.params("startdate")) == {"2000-01-01T00:00:00.000Z"}
        assert [row["uuid"] for row in result.rows] == uuids

    @parameterized.expand(
        [
            ("object_body_without_selector", "campaigns", {"campaigns": [{"uuid": "a"}], "total": 1}, "'campaigns'"),
            ("selector_key_missing", "email_templates", {"templates": [{"uuid": "a"}]}, "'templates'"),
        ]
    )
    def test_an_unexpected_body_fails_on_the_first_page_and_names_its_keys(
        self, _name: str, schema: str, body: dict[str, Any], key: str
    ) -> None:
        result = _driver().run(schema, always(ScriptedResponse(json=body)))

        assert isinstance(result.raised, ValueError)
        assert key in str(result.raised)
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("later_page_repeating_the_page_before", 7, {6: (0, 100), 7: (0, 100)}, ["6", "7"], []),
            ("after_the_last_page", 2, {1: (100, 150)}, ["1"], []),
            ("page_one_counting_from_zero", 1, {0: (0, 100), 1: (100, 150)}, ["0", "1"], list(range(100, 150))),
            (
                "page_one_counting_from_one",
                1,
                {0: (0, 100), 1: (0, 100), 2: (100, 150)},
                ["0", "1", "2"],
                list(range(100, 150)),
            ),
        ]
    )
    def test_resume_writes_no_row_of_an_earlier_page(
        self, _name: str, next_page: int, pages: dict[int, tuple[int, int]], requested: list[str], written: list[int]
    ) -> None:
        def answer(request: Any) -> ScriptedResponse:
            start, stop = pages[int(request.param("page"))]
            return _segments(start, stop)

        result = _driver().run("segments", answer, resume_state=BlueshiftResumeConfig(next_page=next_page))

        assert result.raised is None
        assert result.params("page") == requested
        assert [row["uuid"] for row in result.rows] == [f"s{i}" for i in written]

    @parameterized.expand(
        [
            (
                "bare_list_single_page",
                "tags",
                [ScriptedResponse(json=[{"id": 1}, {"id": 2}])],
                "/api/v1/tag_contexts/list",
            ),
            (
                "wrapped_single_page",
                "subscription_groups",
                [ScriptedResponse(json={"subscription_groups": [{"uuid": "a"}, {"uuid": "b"}]})],
                "/api/v1/subscription_groups",
            ),
            (
                "bare_list_paginated",
                "sms_templates",
                [ScriptedResponse(json=[{"uuid": "a"}, {"uuid": "b"}])],
                "/api/v1/sms_templates.json",
            ),
        ]
    )
    def test_response_shapes_yield_their_rows(
        self, _name: str, schema: str, script: list[ScriptedResponse], path: str
    ) -> None:
        result = _driver().run(schema, script)

        assert result.raised is None
        assert set(result.paths) == {path}
        assert len(result.rows) == 2

    def test_eu_region_calls_the_eu_host(self) -> None:
        result = _driver(region="eu").run("tags", [ScriptedResponse(json=[])])

        assert result.requests[0].origin == "https://api.eu.getblueshift.com"


class TestBlueshiftCampaignStats:
    @parameterized.expand([("server_delay_above_backoff_cap", 120.0, 120.0), ("no_server_delay", None, None)])
    def test_retry_waits_the_delay_the_server_asks_for(
        self, _name: str, retry_after: float | None, expected: float | None
    ) -> None:
        outcome = MagicMock()
        outcome.exception.return_value = BlueshiftRetryableError("status=429", retry_after=retry_after)
        state = MagicMock(outcome=outcome, attempt_number=1)

        wait = _wait_stats(state)

        if expected is None:
            assert 0 <= wait <= MAX_STATS_RETRY_WAIT_SECONDS
        else:
            assert wait == expected

    @parameterized.expand(
        [
            ("watermark_rereads_a_week", {"db_incremental_field_last_value": date(2026, 10, 13)}, "2026-10-06"),
            (
                "resume_beats_watermark",
                {
                    "db_incremental_field_last_value": date(2026, 10, 1),
                    "resume_state": BlueshiftResumeConfig(next_date="2026-10-14"),
                },
                "2026-10-14",
            ),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_walks_one_day_per_request_through_today(self, _name: str, kwargs: dict[str, Any], first_day: str) -> None:
        def answer(request: Any) -> ScriptedResponse:
            day = request.param("start_time")[:10]
            if day == "2026-10-14":
                return ScriptedResponse(json={"campaigns": []})
            idle = {"uuid": "idle", "statistics": {"sends": 0, "revenue": "0.0", "start_time": f"{day}T00:00:00Z"}}
            return ScriptedResponse(json={"campaigns": [_campaign(f"c-{day}"), idle]})

        result = _driver().run(
            "campaign_stats", answer, incremental_field="date", source_cursor=_no_stored_cursor(), **kwargs
        )

        assert result.raised is None
        start_days = [value[:10] for value in result.params("start_time") if value]
        assert start_days[0] == first_day
        assert start_days[-1] == "2026-10-15"
        assert result.requests[0].param("end_time") == f"{start_days[1]}T00:00:00.000Z"
        assert all(row["date"] == row["uuid"][2:] for row in result.rows)
        assert "2026-10-14" not in {row["date"] for row in result.rows}
        assert result.committed_states[-1] == BlueshiftResumeConfig(next_date="2026-10-15")

    @parameterized.expand(
        [
            ("quiet_account_reads_a_week_before_the_cursor", {}, "2026-10-07"),
            (
                "lookback_moves_the_cursor_back",
                {
                    "db_incremental_field_last_value": date(2026, 10, 3),
                    "db_incremental_field_last_value_before_lookback": date(2026, 10, 10),
                },
                "2026-09-30",
            ),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_starts_from_the_stored_cursor_and_advances_it(
        self, _name: str, inputs: dict[str, Any], first_day: str
    ) -> None:
        source = BlueshiftSource()
        cursor = SourceCursorManager(BlueshiftStatsCursor, BlueshiftStatsCursor(next_date="2026-10-14"), source)
        result = SourceDriver(source, BlueshiftSourceConfig(api_key=API_KEY, region="us")).run(
            "campaign_stats",
            always(ScriptedResponse(json={"campaigns": []})),
            incremental_field="date",
            source_cursor=cursor,
            **inputs,
        )

        assert result.raised is None
        assert result.params("start_time")[0] == f"{first_day}T00:00:00.000Z"
        assert result.params("start_time")[-1] == "2026-10-15T00:00:00.000Z"
        assert cursor.staged == BlueshiftStatsCursor(next_date="2026-10-15")

    @time_machine.travel(NOW, tick=False)
    def test_first_sync_backfills_a_year(self) -> None:
        result = _driver().run("campaign_stats", always(ScriptedResponse(json={"campaigns": []})))

        assert result.raised is None
        assert result.requests[0].param("start_time") == "2025-10-15T00:00:00.000Z"
        assert len(result.requests) == 366

    @time_machine.travel(NOW, tick=False)
    def test_a_rate_limited_day_is_retried_rather_than_failing_the_run(self) -> None:
        calls = {"n": 0}

        def answer(_request: Any) -> ScriptedResponse:
            calls["n"] += 1
            if calls["n"] == 1:
                return ScriptedResponse(status=429, json={})
            return ScriptedResponse(json={"campaigns": []})

        result = _driver().run(
            "campaign_stats",
            answer,
            incremental_field="date",
            source_cursor=_no_stored_cursor(),
            db_incremental_field_last_value=date(2026, 10, 15),
        )

        assert result.raised is None
        # One extra request over the plain day-count: the first day's 429 is retried once, then
        # every day (including the retried one) answers cleanly.
        assert len(result.requests) == 9

    @time_machine.travel(NOW, tick=False)
    def test_a_sustained_rate_limit_exhausts_retries_and_raises_the_marker(self) -> None:
        result = _driver().run(
            "campaign_stats",
            always(ScriptedResponse(status=429, json={})),
            incremental_field="date",
            source_cursor=_no_stored_cursor(),
            db_incremental_field_last_value=date(2026, 10, 15),
        )

        assert isinstance(result.raised, BlueshiftRetryableError)
        assert "Blueshift API error (retryable): status=429" in str(result.raised)
        assert len(result.requests) == MAX_STATS_RETRY_ATTEMPTS

    @time_machine.travel(NOW, tick=False)
    def test_rejected_key_fails_the_run_and_keeps_the_key_out_of_logs(self) -> None:
        result = _driver().run(
            "campaign_stats",
            [ScriptedResponse(status=401, json={"errors": "Invalid API key"})],
            incremental_field="date",
            source_cursor=_no_stored_cursor(),
            db_incremental_field_last_value=date(2026, 10, 15),
        )

        assert result.raised is not None
        assert "401 Client Error: Unauthorized for url" in str(result.raised)
        assert {API_KEY, AUTH_VALUE} <= set(result.session_options[0]["redact_values"])


class TestBlueshiftValidateCredentials:
    @parameterized.expand(
        [
            ("source_create", None, "/api/v1/segments/list", "per_page"),
            ("stats_table", "campaign_stats", "/api/v1/campaigns.json", "start_time"),
            ("single_page_table", "tags", "/api/v1/tag_contexts/list", None),
        ]
    )
    def test_probes_the_table_being_configured(
        self, _name: str, schema_name: str | None, path: str, param: str | None
    ) -> None:
        config = BlueshiftSourceConfig(api_key=API_KEY, region="us")
        with scripted_network(always(ScriptedResponse(json={}))) as network:
            valid, _ = BlueshiftSource().validate_credentials(config, team_id=1, schema_name=schema_name)

        assert valid is True
        assert [r.path for r in network.requests_log] == [path]
        if param is not None:
            assert network.requests_log[0].param(param) is not None

    @pytest.mark.parametrize(
        ("status", "schema_name", "expected_valid"),
        [
            (401, None, False),
            (403, None, True),
            (403, "segments", False),
            (500, None, False),
        ],
    )
    def test_maps_probe_status(self, status: int, schema_name: str | None, expected_valid: bool) -> None:
        config = BlueshiftSourceConfig(api_key=API_KEY, region="us")
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            valid, message = BlueshiftSource().validate_credentials(config, team_id=1, schema_name=schema_name)

        assert valid is expected_valid
        assert (message is None) is expected_valid


class TestBlueshiftRetryableErrors:
    @parameterized.expand(
        [
            (
                "exhausted_rate_limit",
                "Blueshift API error (retryable): status=429, url=https://api.getblueshift.com/api/v1/campaigns.json",
            ),
            (
                "exhausted_5xx",
                "Blueshift API error (retryable): status=503, url=https://api.getblueshift.com/api/v1/campaigns.json",
            ),
        ]
    )
    def test_retryable_errors_match_exhausted_retry(self, _name: str, observed_error: str) -> None:
        retryable_errors = BlueshiftSource().get_retryable_errors()
        assert any(key in observed_error for key in retryable_errors)
