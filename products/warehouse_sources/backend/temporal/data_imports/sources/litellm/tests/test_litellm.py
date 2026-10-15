from datetime import UTC, datetime
from typing import Any

import pytest
import time_machine

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.litellm import (
    LiteLLMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.litellm import (
    SPEND_LOGS_UNAVAILABLE_MESSAGE,
    LiteLLMResumeConfig,
    LiteLLMSpendLogsUnavailableError,
    normalize_base_url,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.source import LiteLLMSource

NOW = datetime(2026, 1, 3, 0, 0, tzinfo=UTC)


def _run(schema: str, script: Any, **inputs: Any) -> DriveResult:
    config = LiteLLMSourceConfig(base_url="https://proxy.example.com/litellm/", api_key="sk-master")
    with time_machine.travel(NOW, tick=False):
        return SourceDriver(LiteLLMSource(), config).run(schema, script, **inputs)


def _logs(
    request_ids: list[str], total_pages: int, start_time: str = "2026-01-01T10:00:00.250000Z", capped: bool = False
) -> ScriptedResponse:
    rows = [{"request_id": rid, "startTime": start_time, "spend": 0.01} for rid in request_ids]
    body = {"data": rows, "total": len(rows), "page": 1, "total_pages": total_pages, "total_is_capped": capped}
    return ScriptedResponse(json=body)


def _window(request: RecordedRequest) -> tuple[str | None, str | None, str | None]:
    return request.param("start_date"), request.param("end_date"), request.param("page")


class TestSpendLogs:
    def test_full_refresh_finds_the_oldest_log_then_walks_day_windows_and_pages(self) -> None:
        result = _run(
            "spend_logs",
            [_logs(["oldest"], 9), _logs(["a", "b"], 2), _logs(["c"], 2), _logs(["d"], 1)],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        assert result.paths == ["/litellm/spend/logs/v2"] * 4
        assert [_window(request) for request in result.requests] == [
            ("2000-01-01 00:00:00", "2026-01-03 00:00:00", "1"),
            ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "1"),
            ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "2"),
            ("2026-01-02 10:00:00", "2026-01-03 00:00:00", "1"),
        ]
        assert result.params("page_size") == ["1", "1000", "1000", "1000"]
        assert {(r.param("sort_by"), r.param("sort_order")) for r in result.requests} == {("startTime", "asc")}
        assert result.requests[0].headers["authorization"] == "Bearer sk-master"
        assert [row["request_id"] for row in result.rows] == ["a", "b", "c", "d"]
        assert result.saved_states == [
            LiteLLMResumeConfig(window_start="2026-01-01T10:00:00+00:00", run_end="2026-01-03T00:00:00+00:00", page=2),
            LiteLLMResumeConfig(
                window_start="2026-01-02T10:00:00+00:00",
                run_end="2026-01-03T00:00:00+00:00",
                page=1,
                window_start_seen=True,
            ),
        ]

    def test_incremental_run_starts_at_the_watermark_without_the_oldest_log_lookup(self) -> None:
        result = _run(
            "spend_logs",
            [_logs(["a"], 1)],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-02T18:30:15.900000Z",
        )

        assert result.raised is None
        assert [_window(request) for request in result.requests] == [
            ("2026-01-02 18:30:15", "2026-01-03 00:00:00", "1")
        ]

    def test_empty_window_moves_on_to_the_next_window(self) -> None:
        result = _run(
            "spend_logs",
            [_logs([], 0), _logs(["late"], 1)],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-01T12:00:00Z",
        )

        assert result.raised is None
        assert [_window(request)[:2] for request in result.requests] == [
            ("2026-01-01 12:00:00", "2026-01-02 12:00:00"),
            ("2026-01-02 12:00:00", "2026-01-03 00:00:00"),
        ]
        assert [row["request_id"] for row in result.rows] == ["late"]

    def test_drops_rows_a_later_window_repeats_at_its_start(self) -> None:
        # Both bounds are inclusive, so a row at exactly the first window's end comes back in the second.
        result = _run(
            "spend_logs",
            [
                _logs(["first", "edge"], 1, start_time="2026-01-02T12:00:00Z"),
                ScriptedResponse(
                    json={
                        "data": [
                            {"request_id": "edge", "startTime": "2026-01-02T12:00:00Z"},
                            {"request_id": "later", "startTime": "2026-01-02T13:00:00Z"},
                        ],
                        "total_pages": 1,
                    }
                ),
            ],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-01T12:00:00Z",
        )

        assert result.raised is None
        assert [row["request_id"] for row in result.rows] == ["first", "edge", "later"]

    @pytest.mark.parametrize(("window_start_seen", "expected_ids"), [(False, ["edge", "later"]), (True, ["later"])])
    def test_resumed_window_drops_start_rows_only_after_an_earlier_window(
        self, window_start_seen: bool, expected_ids: list[str]
    ) -> None:
        rows = [
            {"request_id": "edge", "startTime": "2026-01-02T20:00:00Z"},
            {"request_id": "later", "startTime": "2026-01-02T21:00:00Z"},
        ]
        result = _run(
            "spend_logs",
            [ScriptedResponse(json={"data": rows, "total_pages": 2})],
            should_use_incremental_field=False,
            resume_state=LiteLLMResumeConfig(
                window_start="2026-01-02T20:00:00+00:00",
                run_end="2026-01-03T00:00:00+00:00",
                page=2,
                window_start_seen=window_start_seen,
            ),
        )

        assert result.raised is None
        assert [row["request_id"] for row in result.rows] == expected_ids

    def test_keeps_paging_past_a_capped_total(self) -> None:
        full_page = [f"r{index}" for index in range(1000)]
        result = _run(
            "spend_logs",
            [_logs(full_page, 10, capped=True), _logs(["tail"], 10, capped=True)],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-02T20:00:00Z",
            resume_state=LiteLLMResumeConfig(
                window_start="2026-01-02T20:00:00+00:00", run_end="2026-01-03T00:00:00+00:00", page=10
            ),
        )

        assert result.raised is None
        assert result.params("page") == ["10", "11"]
        assert len(result.rows) == 1001

    def test_resume_continues_from_the_saved_window_and_page(self) -> None:
        result = _run(
            "spend_logs",
            [_logs(["c"], 3), _logs(["d"], 3)],
            should_use_incremental_field=False,
            resume_state=LiteLLMResumeConfig(
                window_start="2026-01-02T10:00:00+00:00", run_end="2026-01-02T20:00:00+00:00", page=2
            ),
        )

        assert result.raised is None
        assert [_window(request) for request in result.requests] == [
            ("2026-01-02 10:00:00", "2026-01-02 20:00:00", "2"),
            ("2026-01-02 10:00:00", "2026-01-02 20:00:00", "3"),
        ]

    def test_proxy_without_any_logs_stops_after_the_lookup(self) -> None:
        result = _run("spend_logs", [_logs([], 0)], should_use_incremental_field=False)

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.rows == []

    def test_proxy_without_the_v2_endpoint_fails_with_an_upgrade_message(self) -> None:
        result = _run(
            "spend_logs",
            [ScriptedResponse(status=404, json={"detail": "Not Found"})],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-02T00:00:00Z",
        )

        assert isinstance(result.raised, LiteLLMSpendLogsUnavailableError)
        assert str(result.raised) == SPEND_LOGS_UNAVAILABLE_MESSAGE


class TestListEndpoints:
    def test_keys_walk_pages_until_total_pages(self) -> None:
        result = _run(
            "keys",
            [
                ScriptedResponse(
                    json={
                        "keys": [{"token": "t1", "config": {"model_list": [{"litellm_params": {"api_key": "x"}}]}}],
                        "total_count": 2,
                        "current_page": 1,
                        "total_pages": 2,
                    }
                ),
                ScriptedResponse(
                    json={"keys": [{"token": "t2"}], "total_count": 2, "current_page": 2, "total_pages": 2}
                ),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/litellm/key/list"] * 2
        assert result.params("page") == ["1", "2"]
        assert result.params("size") == ["100", "100"]
        assert result.params("return_full_object") == ["true", "true"]
        assert result.rows == [{"token": "t1"}, {"token": "t2"}]

    @pytest.mark.parametrize(
        ("schema", "body", "expected_rows"),
        [
            (
                "teams",
                [{"team_id": "team-1", "team_alias": "Search", "keys": [{"token": "t1", "config": {"api_key": "x"}}]}],
                [{"team_id": "team-1", "team_alias": "Search"}],
            ),
            (
                "models",
                {"data": [{"model_name": "gpt", "model_info": {"id": "dep-1"}}, {"model_name": "bare"}]},
                [
                    {"model_name": "gpt", "model_info": {"id": "dep-1"}, "model_id": "dep-1"},
                    {"model_name": "bare", "model_id": None},
                ],
            ),
        ],
    )
    def test_single_page_endpoints_shape_rows(
        self, schema: str, body: Any, expected_rows: list[dict[str, Any]]
    ) -> None:
        result = _run(schema, [ScriptedResponse(json=body)])

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.rows == expected_rows


class TestNormalizeBaseUrl:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("proxy.example.com", "https://proxy.example.com"),
            ("https://proxy.example.com:4000/litellm/", "https://proxy.example.com:4000/litellm"),
        ],
    )
    def test_accepts_https_origins_with_a_path_prefix(self, value: str, expected: str) -> None:
        assert normalize_base_url(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "http://proxy.example.com",
            "https://user:pass@proxy.example.com",
            "https://169.254.169.254\\@proxy.example.com",
            "https://169.254.169.254%40proxy.example.com",
            "https://proxy.example.com/?next=1",
            "",
        ],
    )
    def test_rejects_urls_the_host_check_could_misread(self, value: str) -> None:
        with pytest.raises(ValueError):
            normalize_base_url(value)
