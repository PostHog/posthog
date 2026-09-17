from posthog.test.base import BaseTest

from .. import PathsResultsFormatter


class TestPathsResultsFormatter(BaseTest):
    def test_format_paths(self):
        results = [
            {"source": "1_/home", "target": "2_/pricing", "value": 150, "average_conversion_time": 150.0},
            {"source": "1_/home", "target": "2_/docs", "value": 80, "average_conversion_time": 75.0},
            {"source": "2_/pricing", "target": "3_/signup", "value": 120, "average_conversion_time": 45.0},
            {"source": "2_/docs", "target": "3_/signup", "value": 40, "average_conversion_time": 180.0},
        ]

        self.assertEqual(
            PathsResultsFormatter(results).format(),
            "Source|Target|Users|Avg. conversion time\n"
            "1_/home|2_/pricing|150|2m 30s\n"
            "1_/home|2_/docs|80|1m 15s\n"
            "2_/pricing|3_/signup|120|45s\n"
            "2_/docs|3_/signup|40|3m",
        )

    def test_format_empty_results(self):
        self.assertEqual(
            PathsResultsFormatter([]).format(),
            "No data recorded for this time period.",
        )

    def test_format_single_link(self):
        results = [
            {"source": "1_/home", "target": "2_/pricing", "value": 42, "average_conversion_time": 3.5},
        ]

        self.assertEqual(
            PathsResultsFormatter(results).format(),
            "Source|Target|Users|Avg. conversion time\n1_/home|2_/pricing|42|4s",
        )

    def test_format_zero_conversion_time(self):
        results = [
            {"source": "1_/home", "target": "2_/pricing", "value": 10, "average_conversion_time": 0},
        ]

        self.assertEqual(
            PathsResultsFormatter(results).format(),
            "Source|Target|Users|Avg. conversion time\n1_/home|2_/pricing|10|0s",
        )

    def test_format_sub_second_conversion_time(self):
        results = [
            {"source": "1_/home", "target": "2_/pricing", "value": 5, "average_conversion_time": 0.5},
        ]

        self.assertEqual(
            PathsResultsFormatter(results).format(),
            "Source|Target|Users|Avg. conversion time\n1_/home|2_/pricing|5|500ms",
        )

    def test_format_fractional_user_count(self):
        results = [
            {"source": "1_/home", "target": "2_/pricing", "value": 42.5, "average_conversion_time": 60.0},
        ]

        self.assertEqual(
            PathsResultsFormatter(results).format(),
            "Source|Target|Users|Avg. conversion time\n1_/home|2_/pricing|42.5|1m",
        )
