import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.logs.backend.logs_url_params import build_logs_url_params


class TestBuildLogsUrlParams(BaseTest):
    @parameterized.expand(
        [
            ("empty_filters", {}, None, None, ""),
            ("empty_lists", {"severityLevels": [], "serviceNames": []}, None, None, ""),
        ]
    )
    def test_returns_empty_string(self, _name, filters, date_from, date_to, expected):
        assert build_logs_url_params(filters, date_from=date_from, date_to=date_to) == expected

    @parameterized.expand(
        [
            ("severity_levels", {"severityLevels": ["error", "warn"]}, "severityLevels", '["error", "warn"]'),
            ("service_names", {"serviceNames": ["api", "worker"]}, "serviceNames", '["api", "worker"]'),
        ]
    )
    def test_filter_encoded_as_json_array(self, _name, filters, param_key, expected_json):
        result = build_logs_url_params(filters)
        params = parse_qs(result)
        assert params[param_key] == [expected_json]

    @parameterized.expand(
        [
            ("combined", {"severityLevels": ["error"], "serviceNames": ["api"]}, ["severityLevels", "serviceNames"]),
            (
                "with_filter_group",
                {
                    "filterGroup": {
                        "type": "AND",
                        "values": [{"type": "AND", "values": [{"key": "body", "value": "error"}]}],
                    },
                },
                ["filterGroup"],
            ),
        ]
    )
    def test_expected_params_present(self, _name, filters, expected_keys):
        result = build_logs_url_params(filters)
        params = parse_qs(result)
        for key in expected_keys:
            assert key in params

    @parameterized.expand(
        [
            ("no_filter_group_key", {"severityLevels": ["error"]}),
            ("empty_filter_group_values", {"filterGroup": {"type": "AND", "values": [{"type": "AND", "values": []}]}}),
        ]
    )
    def test_empty_filter_group_omitted(self, _name, filters):
        result = build_logs_url_params(filters)
        params = parse_qs(result)
        assert "filterGroup" not in params

    @parameterized.expand(
        [
            (
                "both_timestamps",
                datetime(2026, 4, 6, 14, 50, 0, tzinfo=UTC),
                datetime(2026, 4, 6, 15, 0, 0, tzinfo=UTC),
                {"date_from": "2026-04-06T14:50:00+00:00", "date_to": "2026-04-06T15:00:00+00:00"},
            ),
            (
                "only_date_from",
                datetime(2026, 4, 6, 14, 50, 0, tzinfo=UTC),
                None,
                {"date_from": "2026-04-06T14:50:00+00:00"},
            ),
            (
                "only_date_to",
                None,
                datetime(2026, 4, 6, 15, 0, 0, tzinfo=UTC),
                {"date_to": "2026-04-06T15:00:00+00:00"},
            ),
        ]
    )
    def test_date_range(self, _name, date_from, date_to, expected_range):
        result = build_logs_url_params({}, date_from=date_from, date_to=date_to)
        params = parse_qs(result)
        date_range = json.loads(params["dateRange"][0])
        assert date_range == expected_range

    def test_no_date_range_when_no_timestamps(self):
        result = build_logs_url_params({"severityLevels": ["error"]})
        params = parse_qs(result)
        assert "dateRange" not in params
