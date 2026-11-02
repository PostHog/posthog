from unittest import TestCase

from parameterized import parameterized

from products.experiments.backend.logic.result_stats import MetricTimeseries
from products.experiments.backend.logic.timeseries_text import ExperimentTimeseriesFormatter


def _bayesian_day(
    *,
    baseline_key: str = "control",
    variant_key: str = "test",
    control_n: int = 1000,
    control_sum: float = 50,
    test_n: int = 1010,
    test_sum: float = 70,
    chance_to_win: float | None = 0.92,
    significant: bool | None = True,
    credible_interval: list[float | None] | None = None,
) -> dict:
    return {
        "baseline": {
            "key": baseline_key,
            "number_of_samples": control_n,
            "sum": control_sum,
            "sum_squares": control_sum * 2,
        },
        "variant_results": [
            {
                "key": variant_key,
                "method": "bayesian",
                "number_of_samples": test_n,
                "sum": test_sum,
                "sum_squares": test_sum * 2,
                "chance_to_win": chance_to_win,
                "credible_interval": credible_interval or [0.01, 0.05],
                "significant": significant,
            }
        ],
    }


def _format(response: dict) -> str:
    timeseries = MetricTimeseries.from_stored(status=response["status"], timeseries=response["timeseries"])
    return ExperimentTimeseriesFormatter(timeseries).format()


class TestExperimentTimeseriesFormatter(TestCase):
    def test_empty_timeseries(self):
        result = _format({"status": "pending", "timeseries": {}})
        self.assertEqual(result, "No timeseries data.")

    def test_all_days_pending(self):
        response = {
            "status": "pending",
            "timeseries": {"2026-04-01": None, "2026-04-02": None},
        }
        self.assertEqual(
            _format(response),
            "No completed timeseries data (status: pending).",
        )

    @parameterized.expand(
        [
            (
                "control_baseline",
                "control",
                "test",
                "Variants: control (baseline), test",
                "Date|control n|control mean|test n|test mean|test interval|test chance_to_win|test significant",
            ),
            (
                "non_control_baseline",
                "redesign",
                "control",
                "Variants: redesign (baseline), control",
                "Date|redesign n|redesign mean|control n|control mean|control interval|control chance_to_win|control significant",
            ),
        ]
    )
    def test_bayesian_two_days(
        self, _name: str, baseline_key: str, variant_key: str, expected_variants: str, expected_header: str
    ):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": _bayesian_day(baseline_key=baseline_key, variant_key=variant_key),
                "2026-04-02": _bayesian_day(
                    baseline_key=baseline_key, variant_key=variant_key, test_sum=80, chance_to_win=0.97
                ),
            },
        }
        out = _format(response)
        lines = out.splitlines()
        self.assertEqual(lines[0], "Method: bayesian")
        self.assertEqual(lines[1], expected_variants)
        self.assertEqual(lines[2], "Status: completed")
        self.assertEqual(lines[3], expected_header)
        self.assertEqual(lines[4], "2026-04-01|1000|0.05|1010|0.069307|0.01..0.05|0.92|true")
        self.assertEqual(lines[5], "2026-04-02|1000|0.05|1010|0.079208|0.01..0.05|0.97|true")

    @parameterized.expand(
        [
            ("null_day", None, "2026-04-02|—"),
            (
                "missing_required_stat",
                {"baseline": {"key": "control", "number_of_samples": 1000, "sum": 50}, "variant_results": []},
                "2026-04-02|—",
            ),
            (
                "interval_with_null_bound",
                _bayesian_day(credible_interval=[-0.02, None]),
                "2026-04-02|1000|0.05|1010|0.069307|N/A|0.92|true",
            ),
            (
                "cached_response_fields",
                {**_bayesian_day(), "is_cached": True, "cache_key": "cache_abc", "timezone": "UTC"},
                "2026-04-02|1000|0.05|1010|0.069307|0.01..0.05|0.92|true",
            ),
            (
                "retired_nested_field",
                {
                    "baseline": {**_bayesian_day()["baseline"], "main_covariate_sum_product": None},
                    "variant_results": [{**_bayesian_day()["variant_results"][0], "main_covariate_sum_product": None}],
                },
                "2026-04-02|1000|0.05|1010|0.069307|0.01..0.05|0.92|true",
            ),
        ]
    )
    def test_stored_day_shapes(self, _name: str, stored_day: dict | None, expected_row: str):
        response = {
            "status": "partial",
            "timeseries": {
                "2026-04-01": _bayesian_day(),
                "2026-04-02": stored_day,
                "2026-04-03": _bayesian_day(test_sum=90, chance_to_win=0.99),
            },
        }
        out = _format(response)
        lines = out.splitlines()
        self.assertEqual(lines[5], expected_row)
        self.assertTrue(lines[6].startswith("2026-04-03|"))

    def test_frequentist_uses_p_value_and_confidence_interval(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": {
                    "baseline": {"key": "control", "number_of_samples": 800, "sum": 40, "sum_squares": 80},
                    "variant_results": [
                        {
                            "key": "test",
                            "method": "frequentist",
                            "number_of_samples": 820,
                            "sum": 60,
                            "sum_squares": 120,
                            "p_value": 0.012,
                            "confidence_interval": [0.005, 0.04],
                            "significant": True,
                        }
                    ],
                },
            },
        }
        out = _format(response)
        lines = out.splitlines()
        self.assertEqual(lines[0], "Method: frequentist")
        self.assertIn("test p_value", lines[3])
        self.assertEqual(lines[4], "2026-04-01|800|0.05|820|0.073171|0.005..0.04|0.012|true")

    def test_handles_missing_variant_fields(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": {
                    "baseline": {"key": "control", "number_of_samples": 0, "sum": 0, "sum_squares": 0},
                    "variant_results": [
                        {
                            "key": "test",
                            "method": "bayesian",
                            "number_of_samples": 0,
                            "sum": 0,
                            "sum_squares": 0,
                            "chance_to_win": None,
                            "significant": None,
                        }
                    ],
                },
            },
        }
        out = _format(response)
        lines = out.splitlines()
        self.assertEqual(lines[4], "2026-04-01|0|N/A|0|N/A|N/A|N/A|N/A")

    def test_multi_variant_ordering(self):
        response = {
            "status": "completed",
            "timeseries": {
                "2026-04-01": {
                    "baseline": {"key": "control", "number_of_samples": 1000, "sum": 50, "sum_squares": 100},
                    "variant_results": [
                        {
                            "key": "blue",
                            "method": "bayesian",
                            "number_of_samples": 1000,
                            "sum": 60,
                            "sum_squares": 120,
                            "chance_to_win": 0.6,
                            "credible_interval": [0.0, 0.1],
                            "significant": False,
                        },
                        {
                            "key": "green",
                            "method": "bayesian",
                            "number_of_samples": 1010,
                            "sum": 80,
                            "sum_squares": 160,
                            "chance_to_win": 0.95,
                            "credible_interval": [0.02, 0.08],
                            "significant": True,
                        },
                    ],
                },
            },
        }
        out = _format(response)
        lines = out.splitlines()
        self.assertEqual(lines[1], "Variants: control (baseline), blue, green")
        self.assertIn("blue chance_to_win", lines[3])
        self.assertIn("green chance_to_win", lines[3])
