import json
from pathlib import Path
from tempfile import TemporaryDirectory

from unittest import TestCase

from products.signals.backend.scout_harness.eval_environment.traces import load_trace_inputs


class TestTraceInputs(TestCase):
    def test_reads_stop_at_first_unrecognized_call(self) -> None:
        def call(index: int, command: str) -> list[dict]:
            return [
                {
                    "timestamp": "2030-01-01T00:00:00Z",
                    "notification": {
                        "params": {
                            "update": {
                                "sessionUpdate": "tool_call",
                                "toolCallId": str(index),
                                "rawInput": {"command": command},
                            }
                        }
                    },
                },
                {
                    "notification": {
                        "params": {
                            "update": {
                                "sessionUpdate": "tool_call_update",
                                "toolCallId": str(index),
                                "status": "completed",
                                "rawOutput": {"content": [{"type": "text", "text": "observed"}]},
                            }
                        }
                    }
                },
            ]

        with TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "logs").mkdir()
            events = [
                *call(1, 'call notes-list {"limit": 2}'),
                *call(2, "call report-write {}"),
                *call(3, "call notes-list {}"),
            ]
            (path / "logs/000000.json").write_text(json.dumps(events))
            (path / "log-pages.json").write_text(
                json.dumps(
                    {
                        "total_events": len(events),
                        "pages": [
                            {"path": "runs/example/logs/000000.json", "first_event_index": 0, "returned": len(events)}
                        ],
                    }
                )
            )
            # These files deliberately cannot be decoded; extracting reads must never consult them.
            (path / "result.json").write_text("private heldout")
            result = load_trace_inputs(path, read_tools={"notes-list"})

        self.assertEqual(result.first_write_index, 2)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].arguments, {"limit": 2})
        self.assertEqual(result.observations[0].text, "observed")
