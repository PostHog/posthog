import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

VIEWS = "products.tracing.backend.presentation.views"

ENDPOINTS: list[tuple[str, str, dict[str, str], object]] = [
    ("service-names", "run_service_names_query", {}, []),
    ("attributes", "run_attribute_names_query", {}, ([], 0)),
    ("values", "run_attribute_values_query", {"key": "http.method"}, []),
]


class TestTracingGetDateParams(APIBaseTest):
    def _get(self, path: str, runner: str, params: dict, return_value):
        with patch(f"{VIEWS}.{runner}", return_value=return_value) as run:
            response = self.client.get(f"/api/projects/{self.team.id}/tracing/spans/{path}/", params)
        return response, run

    @parameterized.expand(ENDPOINTS)
    def test_malformed_date_range_is_a_400_with_an_example(self, path, runner, extra, return_value):
        response, run = self._get(path, runner, {"dateRange": "{date_from: -1h}", **extra}, return_value)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('{"date_from": "-1h"}', json.dumps(response.json()).replace('\\"', '"'))
        run.assert_not_called()

    @parameterized.expand(ENDPOINTS)
    def test_date_range_must_be_an_object(self, path, runner, extra, return_value):
        response, run = self._get(path, runner, {"dateRange": '"-1h"', **extra}, return_value)
        self.assertEqual(response.status_code, 400, response.content)
        run.assert_not_called()

    @parameterized.expand(ENDPOINTS)
    def test_date_range_values_must_be_strings(self, path, runner, extra, return_value):
        response, run = self._get(path, runner, {"dateRange": '{"date_from": 5}', **extra}, return_value)
        self.assertEqual(response.status_code, 400, response.content)
        run.assert_not_called()

    @parameterized.expand(ENDPOINTS)
    def test_explicit_date_option_is_still_accepted(self, path, runner, extra, return_value):
        response, run = self._get(
            path, runner, {"dateRange": '{"date_from": "-6h", "explicitDate": true}', **extra}, return_value
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(run.call_args.kwargs["date_range"].date_from, "-6h")

    @parameterized.expand(ENDPOINTS)
    def test_json_date_range_still_works(self, path, runner, extra, return_value):
        response, run = self._get(path, runner, {"dateRange": '{"date_from": "-6h"}', **extra}, return_value)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(run.call_args.kwargs["date_range"].date_from, "-6h")

    @parameterized.expand(ENDPOINTS)
    def test_flat_date_params(self, path, runner, extra, return_value):
        response, run = self._get(
            path, runner, {"date_from": "-30m", "date_to": "2026-06-02T09:00:00Z", **extra}, return_value
        )
        self.assertEqual(response.status_code, 200, response.content)
        date_range = run.call_args.kwargs["date_range"]
        self.assertEqual((date_range.date_from, date_range.date_to), ("-30M", "2026-06-02T09:00:00Z"))

    @parameterized.expand(ENDPOINTS)
    def test_date_range_wins_over_flat_params(self, path, runner, extra, return_value):
        response, run = self._get(
            path, runner, {"dateRange": '{"date_from": "-6h"}', "date_from": "-2d", **extra}, return_value
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(run.call_args.kwargs["date_range"].date_from, "-6h")

    @parameterized.expand(ENDPOINTS)
    def test_no_dates_defaults_to_the_last_hour(self, path, runner, extra, return_value):
        response, run = self._get(path, runner, extra, return_value)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(run.call_args.kwargs["date_range"].date_from, "-1h")

    @parameterized.expand(ENDPOINTS)
    def test_bad_flat_value_is_a_400(self, path, runner, extra, return_value):
        response, run = self._get(path, runner, {"date_from": "last tuesday", **extra}, return_value)
        self.assertEqual(response.status_code, 400, response.content)
        run.assert_not_called()
