import base64
from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest
import time_machine

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.blueshift.blueshift import (
    BlueshiftResumeConfig,
    BlueshiftStatsCursor,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.blueshift.source import BlueshiftSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.blueshift import (
    BlueshiftSourceConfig,
)

API_KEY = "test-user-api-key"
AUTH_VALUE = "Basic " + base64.b64encode(f"{API_KEY}:".encode()).decode()
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)


def _driver(region: Literal["us", "eu"] = "us") -> SourceDriver:
    return SourceDriver(BlueshiftSource(), BlueshiftSourceConfig(api_key=API_KEY, region=region))


def _no_stored_cursor() -> SourceCursorManager[BlueshiftStatsCursor]:
    return SourceCursorManager(BlueshiftStatsCursor, None, BlueshiftSource())


def _campaign(uuid: str) -> dict[str, Any]:
    return {"uuid": uuid, "name": f"Campaign {uuid}", "statistics": {"sends": 10, "opens": 4}}


class TestBlueshiftLists:
    def test_paginated_list_walks_pages_until_an_empty_page(self) -> None:
        result = _driver().run(
            "segments",
            [
                ScriptedResponse(json={"segments": [{"uuid": f"s{i}"} for i in range(100)]}),
                ScriptedResponse(json={"segments": [{"uuid": "s100"}]}),
                ScriptedResponse(json={"segments": []}),
            ],
        )

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.params("per_page") == ["100", "100", "100"]
        assert {r.headers.get("authorization") for r in result.requests} == {AUTH_VALUE}
        assert len(result.rows) == 101
        assert result.saved_states == [BlueshiftResumeConfig(next_page=2), BlueshiftResumeConfig(next_page=3)]

    def test_resume_starts_from_the_saved_page(self) -> None:
        result = _driver().run(
            "email_templates",
            [ScriptedResponse(json={"template": []})],
            resume_state=BlueshiftResumeConfig(next_page=7),
        )

        assert result.params("page") == ["7"]

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
                [ScriptedResponse(json=[{"uuid": "a"}, {"uuid": "b"}]), ScriptedResponse(json=[])],
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
            return ScriptedResponse(json={"campaigns": [_campaign(f"c-{day}")]})

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
