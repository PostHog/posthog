import unittest

from parameterized import parameterized

from products.workflows.evals.compare_email_models import parse_cli_result


class TestEmailModelComparison(unittest.TestCase):
    @parameterized.expand(
        [
            ("not_json", "I could not write that email"),
            ("missing", "{}"),
            ("null", '{"emails":null}'),
            ("not_objects", '{"emails":[null,"email"]}'),
        ]
    )
    def test_records_malformed_drafts_without_losing_measurements(self, name: str, raw: str) -> None:
        result = parse_cli_result(
            {
                "result": raw,
                "modelUsage": {"claude-sonnet-5-5": {}},
                "total_cost_usd": 0.034,
                "duration_api_ms": 1234,
                "usage": {},
            },
            "claude-sonnet-5-5",
        )
        self.assertEqual(result["generation_cost_usd"], 0.034)
        self.assertEqual(result["latency_ms"], 1234)
        self.assertEqual(result["raw_draft"], raw)
        self.assertIsNone(result["emails"])

    def test_preserves_reported_cost_and_api_latency(self) -> None:
        result = parse_cli_result(
            {
                "is_error": False,
                "stop_reason": "end_turn",
                "modelUsage": {"claude-sonnet-5-5": {"costBasis": "list"}},
                "total_cost_usd": 0.034,
                "duration_api_ms": 1234,
                "duration_ms": 2000,
                "usage": {"input_tokens": 15, "output_tokens": 40},
                "result": '```json\n{"emails":[{"subject":"Start your garden","text":"Add your first bed"}]}\n```',
            },
            "claude-sonnet-5-5",
        )
        self.assertEqual(result["generation_cost_usd"], 0.034)
        self.assertEqual(result["latency_ms"], 1234)
        self.assertEqual(result["emails"][0]["subject"], "Start your garden")

    @parameterized.expand(
        [
            ("api_error", {"is_error": True}),
            ("truncated", {"stop_reason": "max_tokens"}),
            ("substituted", {"modelUsage": {"claude-sonnet-5": {}}}),
        ]
    )
    def test_rejects_unusable_measurements(self, name: str, payload: dict) -> None:
        with self.assertRaises(RuntimeError):
            parse_cli_result(payload, "claude-sonnet-5-5")
