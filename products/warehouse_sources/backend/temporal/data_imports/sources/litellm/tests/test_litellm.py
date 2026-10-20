from datetime import UTC, datetime, timedelta
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


RUN_END = "2026-01-03 00:00:00"
FIRST = datetime(2026, 1, 1, 10, 0, 0, 250000, tzinfo=UTC)


def _log(request_id: str, start: datetime) -> dict[str, Any]:
    return {"request_id": request_id, "startTime": start.isoformat().replace("+00:00", "Z"), "spend": 0.01}


def _logs(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "total": len(rows), "page": 1, "total_pages": 1})


def _full_page(prefix: str, start: datetime, step_seconds: int = 1) -> list[dict[str, Any]]:
    return [_log(f"{prefix}{i}", start + timedelta(seconds=i * step_seconds)) for i in range(100)]


def _request(request: RecordedRequest) -> tuple[str | None, str | None, str | None]:
    return request.param("start_date"), request.param("end_date"), request.param("page")


class TestSpendLogs:
    def test_full_refresh_moves_start_date_to_the_last_log_of_each_full_page(self) -> None:
        first_page = _full_page("r", FIRST)
        last = first_page[-1]
        result = _run(
            "spend_logs",
            [
                _logs([first_page[0]]),
                _logs(first_page),
                _logs([last, _log("next", FIRST + timedelta(minutes=5))]),
                _logs([]),
            ],
            should_use_incremental_field=False,
        )

        assert result.raised is None
        # The oldest-log lookup, then requests that each cover at most a day after the cursor.
        assert [_request(request) for request in result.requests] == [
            ("2000-01-01 00:00:00", RUN_END, "1"),
            ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "1"),
            ("2026-01-01 10:01:39", "2026-01-02 10:01:39", "1"),
            ("2026-01-02 10:01:39", RUN_END, "1"),
        ]
        assert result.params("page_size") == ["2", "100", "100", "100"]
        assert {(r.param("sort_by"), r.param("sort_order")) for r in result.requests} == {("startTime", "asc")}
        assert result.requests[0].headers["authorization"] == "Bearer sk-master"
        assert [row["request_id"] for row in result.rows] == [f"r{i}" for i in range(100)] + ["next"]
        assert result.saved_states == [
            LiteLLMResumeConfig(
                cursor="2026-01-01T10:01:39+00:00",
                run_end="2026-01-03T00:00:00+00:00",
                page=1,
                seen_request_ids=("r99",),
            ),
            LiteLLMResumeConfig(cursor="2026-01-02T10:01:39+00:00", run_end="2026-01-03T00:00:00+00:00", page=1),
        ]

    def test_incremental_run_starts_at_the_watermark_second(self) -> None:
        result = _run(
            "spend_logs",
            [_logs([_log("a", FIRST)])],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-02T18:30:15.900000Z",
        )

        assert result.raised is None
        assert [_request(request) for request in result.requests] == [("2026-01-02 18:30:15", RUN_END, "1")]

    @pytest.mark.parametrize(("next_log", "expected_requests"), [(True, 3), (False, 2)])
    def test_empty_day_jumps_to_the_next_log(self, next_log: bool, expected_requests: int) -> None:
        later = datetime(2026, 1, 2, 12, 0, 0, 500000, tzinfo=UTC)
        result = _run(
            "spend_logs",
            [_logs([]), _logs([_log("late", later)] if next_log else []), _logs([_log("late", later)])],
            incremental_field="startTime",
            db_incremental_field_last_value="2025-06-01T00:00:00Z",
        )

        assert result.raised is None
        assert [_request(request) for request in result.requests] == [
            ("2025-06-01 00:00:00", "2025-06-02 00:00:00", "1"),
            ("2025-06-02 00:00:00", RUN_END, "1"),
            ("2026-01-02 12:00:00", RUN_END, "1"),
        ][:expected_requests]
        assert [row["request_id"] for row in result.rows] == (["late"] if next_log else [])

    def test_next_log_before_the_empty_window_still_moves_the_walk_forward(self) -> None:
        stale = datetime(2025, 1, 1, tzinfo=UTC)
        result = _run(
            "spend_logs",
            [_logs([]), _logs([_log("stale", stale)]), _logs([])],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )

        assert result.raised is None
        assert [_request(request)[:2] for request in result.requests] == [
            ("2026-01-01 00:00:00", "2026-01-02 00:00:00"),
            ("2026-01-02 00:00:00", RUN_END),
            ("2026-01-02 00:00:00", RUN_END),
        ]

    def test_newest_first_proxy_is_caught_before_a_full_refresh_starts(self) -> None:
        result = _run(
            "spend_logs",
            [_logs([_log("newer", FIRST + timedelta(minutes=1)), _log("older", FIRST)])],
            should_use_incremental_field=False,
        )

        assert isinstance(result.raised, LiteLLMSpendLogsUnavailableError)
        assert len(result.requests) == 1

    def test_full_page_inside_one_second_steps_by_page(self) -> None:
        same_second = [_log(f"s{i}", FIRST) for i in range(100)]
        result = _run(
            "spend_logs",
            [_logs(same_second), _logs([_log("after", FIRST + timedelta(seconds=2))]), _logs([])],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-01T10:00:00Z",
        )

        assert result.raised is None
        assert [_request(request) for request in result.requests][:2] == [
            ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "1"),
            ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "2"),
        ]
        assert len(result.rows) == 101

    def test_resume_drops_logs_the_last_page_already_yielded(self) -> None:
        result = _run(
            "spend_logs",
            [_logs([_log("seen", FIRST), _log("new", FIRST)]), _logs([])],
            should_use_incremental_field=False,
            resume_state=LiteLLMResumeConfig(
                cursor="2026-01-01T10:00:00+00:00",
                run_end="2026-01-02T20:00:00+00:00",
                page=1,
                seen_request_ids=("seen",),
            ),
        )

        assert result.raised is None
        assert _request(result.requests[0]) == ("2026-01-01 10:00:00", "2026-01-02 10:00:00", "1")
        assert [row["request_id"] for row in result.rows] == ["new"]

    def test_proxy_without_any_logs_makes_one_request(self) -> None:
        result = _run("spend_logs", [_logs([])], should_use_incremental_field=False)

        assert result.raised is None
        assert len(result.requests) == 1
        assert result.rows == []

    @pytest.mark.parametrize(
        "response",
        [
            ScriptedResponse(status=404, json={"detail": "Not Found"}),
            # LiteLLM before 1.95 caps page_size at 100; FastAPI answers a larger one with 422.
            ScriptedResponse(status=422, json={"detail": [{"type": "less_than_equal", "loc": ["query", "page_size"]}]}),
            # LiteLLM versions that ignore sort_order return the newest logs first.
            _logs([_log("newer", FIRST + timedelta(minutes=1)), _log("older", FIRST)]),
        ],
    )
    def test_unsupported_proxy_fails_with_an_upgrade_message(self, response: ScriptedResponse) -> None:
        result = _run(
            "spend_logs",
            [response],
            incremental_field="startTime",
            db_incremental_field_last_value="2026-01-02T00:00:00Z",
        )

        assert isinstance(result.raised, LiteLLMSpendLogsUnavailableError)
        assert str(result.raised) == SPEND_LOGS_UNAVAILABLE_MESSAGE
        assert result.rows == []


_METADATA = {
    "logging": [
        {"callback_name": "langfuse", "callback_vars": {"langfuse_secret_key": "sk-lf-1", "langfuse_host": "h"}}
    ],
    "callback_settings": {"callback_vars": {"langsmith_api_key": "ls-1"}},
    "secret_manager_settings": {"aws_secret_access_key": "aws-secret"},
    "owner": "growth",
}
_REDACTED_METADATA = {
    "logging": [
        {
            "callback_name": "langfuse",
            "callback_vars": {"langfuse_secret_key": "[redacted by PostHog]", "langfuse_host": "[redacted by PostHog]"},
        }
    ],
    "callback_settings": {"callback_vars": {"langsmith_api_key": "[redacted by PostHog]"}},
    "owner": "growth",
}


class TestListEndpoints:
    def test_keys_walk_pages_and_drop_credentials(self) -> None:
        result = _run(
            "keys",
            [
                ScriptedResponse(
                    json={
                        "keys": [
                            {
                                "token": "t1",
                                "config": {"model_list": [{"litellm_params": {"api_key": "x"}}]},
                                "metadata": _METADATA,
                            }
                        ],
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
        assert result.rows == [{"token": "t1", "metadata": _REDACTED_METADATA}, {"token": "t2"}]
        # Responses are captured before the row map masks them, so capture stays off.
        assert {options.get("capture") for options in result.session_options} == {False}

    def test_teams_page_through_v2_and_drop_credentials(self) -> None:
        team = {"team_id": "team-1", "metadata": _METADATA, "keys": [{"token": "t1", "config": {"api_key": "x"}}]}
        result = _run("teams", [ScriptedResponse(json={"teams": [team], "total": 1, "page": 1, "total_pages": 1})])

        assert result.raised is None
        assert result.paths == ["/litellm/v2/team/list"]
        assert result.params("page_size") == ["100"]
        assert result.rows == [{"team_id": "team-1", "metadata": _REDACTED_METADATA}]
        assert {options.get("capture") for options in result.session_options} == {False}

    def test_models_lift_the_deployment_id(self) -> None:
        body = {"data": [{"model_name": "gpt", "model_info": {"id": "dep-1"}}, {"model_name": "bare"}]}
        result = _run("models", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert result.rows == [
            {"model_name": "gpt", "model_info": {"id": "dep-1"}, "model_id": "dep-1"},
            {"model_name": "bare", "model_id": None},
        ]


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
