import json
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.subscriptions.backend.temporal.query_results_summary import (
    MAX_CONDENSATION_INPUT_LENGTH,
    condense_query_results,
)


class TestCondenseQueryResults:
    @parameterized.expand(
        [
            ("valid", "All returned rows cover the query period.", "stop", 1),
            ("too_long", "x" * 2_001, "stop", 2),
            ("empty", "", "stop", 2),
            ("incomplete", "Partial sentence", "length", 2),
        ]
    )
    def test_full_input_and_output_validation(
        self, _name: str, first_content: str, finish_reason: str, expected_calls: int
    ) -> None:
        rows = [
            ["example_action", {"details": "sample" * 50}, f"2026-01-01T00:{index:02d}:00+00:00"] for index in range(25)
        ]
        rows[-1][0] = "example_failure"
        query_results = {
            "result": rows,
            "columns": ["event", "properties", "timestamp"],
            "resolved_date_range": {"date_from": "2026-01-01", "date_to": "2026-01-02"},
            "has_more": True,
        }
        accepted_content = "25 returned rows include example_failure. Additional results exist."
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            SimpleNamespace(
                choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content=first_content))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=accepted_content))]
            ),
        ]

        with patch(
            "products.subscriptions.backend.temporal.query_results_summary._get_openai_client", return_value=client
        ):
            summary = condense_query_results("EventsQuery", query_results)

        assert len(summary) <= 2_000
        assert client.chat.completions.create.call_count == expected_calls
        if expected_calls == 2:
            assert summary == accepted_content
        message = client.chat.completions.create.call_args_list[0].kwargs["messages"][1]["content"]
        payload = json.loads(message.removeprefix("<query_results>\n").removesuffix("\n</query_results>"))
        assert payload["rows"] == rows
        assert payload["event_statistics"]["counts_by_event"] == {"example_action": 24, "example_failure": 1}
        assert payload["event_statistics"]["first_timestamp"] == "2026-01-01T00:00:00+00:00"
        assert payload["event_statistics"]["last_timestamp"] == "2026-01-01T00:24:00+00:00"
        assert payload["event_statistics"]["span_seconds"] == 1_440
        assert payload["event_statistics"]["time_ranges_by_event"] == {
            "example_action": {
                "first_timestamp": "2026-01-01T00:00:00+00:00",
                "last_timestamp": "2026-01-01T00:23:00+00:00",
                "span_seconds": 1_380,
            },
            "example_failure": {
                "first_timestamp": "2026-01-01T00:24:00+00:00",
                "last_timestamp": "2026-01-01T00:24:00+00:00",
                "span_seconds": 0,
            },
        }
        assert payload["has_more"] is True
        assert payload["resolved_date_range"] == query_results["resolved_date_range"]
        assert client.chat.completions.create.call_args.kwargs["posthog_privacy_mode"] is True

    def test_rejects_invalid_summary_without_cutting_it(self) -> None:
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="x" * 2_001))]
        )
        with patch(
            "products.subscriptions.backend.temporal.query_results_summary._get_openai_client", return_value=client
        ):
            with pytest.raises(ValueError, match="condensed summary"):
                condense_query_results("EventsQuery", {"result": [["example_action"]]})

    def test_rejects_oversized_input_without_cutting_rows(self) -> None:
        with pytest.raises(ValueError, match="input limit"):
            condense_query_results("EventsQuery", {"result": [["x" * MAX_CONDENSATION_INPUT_LENGTH]]})
