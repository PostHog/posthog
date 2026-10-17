import json
import datetime as dt

from unittest import TestCase
from unittest.mock import patch

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute

from products.tracing.backend.redaction import FILTERED, redact_attribute_value
from products.tracing.backend.tests.test_keyset_pagination import _b64, _TraceSpansTestBase

FAKE_TOKEN = "fake-test-token-0001"
DATE_RANGE = {"date_from": "2026-06-02T07:00:00Z", "date_to": "2026-06-02T09:00:00Z"}
TRACE_HEX = (1).to_bytes(16, "big").hex()


class TestRedactAttributeValue(TestCase):
    @parameterized.expand(
        [
            ("authorization_header", "http.request.header.authorization", f"Bearer {FAKE_TOKEN}", FILTERED),
            ("cookie_header", "http.request.header.cookie", "sid=abc123; theme=dark", FILTERED),
            ("proxy_header", "http.request.header.x-forwarded-authorization", FAKE_TOKEN, FILTERED),
            ("api_key_header", "http.request.header.x_api_key", FAKE_TOKEN, FILTERED),
            ("plain_password_key", "db.password", "hunter2", FILTERED),
            (
                "bearer_in_free_text",
                "http.raw_headers",
                f"Authorization: Bearer {FAKE_TOKEN}",
                f"Authorization: Bearer {FILTERED}",
            ),
            ("ordinary_header", "http.request.header.content-type", "application/json", "application/json"),
            ("token_count_metric", "llm.token_count.prompt", "120", "120"),
            ("already_filtered", "http.request.header.cookie", FILTERED, FILTERED),
        ]
    )
    def test_redacts_flat_values(self, _name: str, key: str, value: str, expected: str) -> None:
        assert redact_attribute_value(key, value) == expected

    def test_redacts_json_encoded_header_map(self) -> None:
        headers = {
            "Authorization": f"Bearer {FAKE_TOKEN}",
            "Cookie": "sid=abc123",
            "Accept": "application/json",
            "nested": {"X-Auth-Token": FAKE_TOKEN, "X-Request-Id": "req-1"},
        }
        redacted = json.loads(redact_attribute_value("http.request.headers", json.dumps(headers)))
        assert redacted == {
            "Authorization": FILTERED,
            "Cookie": FILTERED,
            "Accept": "application/json",
            "nested": {"X-Auth-Token": FILTERED, "X-Request-Id": "req-1"},
        }

    def test_keeps_json_without_credentials_byte_for_byte(self) -> None:
        value = '{"Accept":"application/json"}'
        assert redact_attribute_value("http.request.headers", value) == value


class TestSpanEndpointsRedactForMcp(_TraceSpansTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls._recreate_trace_spans_tables()
        ts = dt.datetime(2026, 6, 2, 8, 0, 0)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        end_str = (ts + dt.timedelta(milliseconds=5)).strftime("%Y-%m-%d %H:%M:%S.%f")
        header_map = json.dumps({"Authorization": f"Bearer {FAKE_TOKEN}", "Accept": "*/*"}).replace("'", "\\'")
        sync_execute(
            "INSERT INTO trace_spans (uuid, team_id, trace_id, span_id, parent_span_id, name, kind, "
            "timestamp, end_time, observed_timestamp, status_code, service_name, attributes_map_str, "
            "resource_attributes) VALUES "
            "("
            f"'019e8754-0000-0000-0000-000000000001', {cls.team.id}, '{_b64((1).to_bytes(16, 'big'))}', "
            f"'{_b64((1).to_bytes(8, 'big'))}', '', 'GET /api', 2, '{ts_str}', '{end_str}', '{ts_str}', 0, 'web', "
            f"map('http.request.header.authorization__str', 'Bearer {FAKE_TOKEN}', "
            f"'http.request.headers__str', '{header_map}', 'http.method__str', 'POST'), "
            "map('service.version', '1.2.3'))"
        )

    def _fetch_span(self, endpoint: str, *, is_mcp: bool) -> dict:
        url = f"/api/projects/{self.team.id}/tracing/spans/{endpoint}/"
        body: dict = {"dateRange": DATE_RANGE}
        if endpoint == "query":
            body = {"query": body}
        with patch("products.tracing.backend.presentation.views.is_mcp_request", return_value=is_mcp):
            response = self.client.post(url, body, format="json")
        assert response.status_code == 200, response.content
        results = response.json()["results"]
        assert len(results) == 1
        return results[0]

    @parameterized.expand([("query", "query"), ("trace", f"trace/{TRACE_HEX}")])
    def test_mcp_responses_redact_credentials(self, _name: str, endpoint: str) -> None:
        attributes = self._fetch_span(endpoint, is_mcp=True)["attributes"]

        assert FAKE_TOKEN not in json.dumps(attributes)
        assert attributes["http.request.header.authorization"] == FILTERED
        assert json.loads(attributes["http.request.headers"]) == {"Authorization": FILTERED, "Accept": "*/*"}
        assert attributes["http.method"] == "POST"

    @parameterized.expand([("query", "query"), ("trace", f"trace/{TRACE_HEX}")])
    def test_non_mcp_responses_keep_attributes(self, _name: str, endpoint: str) -> None:
        attributes = self._fetch_span(endpoint, is_mcp=False)["attributes"]

        assert attributes["http.request.header.authorization"] == f"Bearer {FAKE_TOKEN}"
