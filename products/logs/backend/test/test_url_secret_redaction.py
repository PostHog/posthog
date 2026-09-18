import json
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import status

from posthog.auth import MCP_USER_AGENT_MARKER
from posthog.clickhouse.client import sync_execute

from products.logs.backend.url_secret_redaction import redact_url_secrets

OAUTH_CODE = "fake-oauth-code-1"
CALLBACK_URL = f"https://app.example.com/oauth/callback?code={OAUTH_CODE}&state=s1&scope=read"
REDACTED_CALLBACK_URL = "https://app.example.com/oauth/callback?code=[redacted]&state=s1&scope=read"

DATE_RANGE = {"date_from": "2026-03-01T09:00:00Z", "date_to": "2026-03-01T11:00:00Z"}


class TestRedactUrlSecrets(SimpleTestCase):
    @parameterized.expand(
        [
            ("oauth_code", CALLBACK_URL, REDACTED_CALLBACK_URL),
            (
                "implicit_grant_fragment",
                "https://app.example.com/#access_token=t1&expires_in=3600",
                "https://app.example.com/#access_token=[redacted]&expires_in=3600",
            ),
            (
                "api_key_in_log_line",
                'msg="upstream call" url=https://api.example.com/v1/items?api_key=k1&page=2 status=200',
                'msg="upstream call" url=https://api.example.com/v1/items?api_key=[redacted]&page=2 status=200',
            ),
            (
                "presigned_link",
                "https://files.example.com/f.csv?X-Amz-Signature=abcdef&X-Amz-Expires=900",
                "https://files.example.com/f.csv?X-Amz-Signature=[redacted]&X-Amz-Expires=900",
            ),
            (
                "bare_query_string_attribute",
                "client_secret=cs1&client_id=ci1",
                "client_secret=[redacted]&client_id=ci1",
            ),
            (
                "separator_spellings",
                "https://app.example.com/cb?access-token=t1&accessToken=t2",
                "https://app.example.com/cb?access-token=[redacted]&accessToken=[redacted]",
            ),
            ("no_query_string", "https://app.example.com/oauth/callback", "https://app.example.com/oauth/callback"),
            # A message that reads like a query string must survive, or redaction eats log text.
            (
                "plain_message",
                "request failed with code=503 after 2 retries",
                "request failed with code=503 after 2 retries",
            ),
            # A name that only reads like a credential must keep its value, or an agent loses the
            # parameters it investigates with.
            (
                "benign_names",
                "https://app.example.com/posts?author=jane&sort_key=name",
                "https://app.example.com/posts?author=jane&sort_key=name",
            ),
            ("empty_value", "https://app.example.com/cb?code=&state=s1", "https://app.example.com/cb?code=&state=s1"),
        ]
    )
    def test_redaction(self, _name, text, expected):
        self.assertEqual(redact_url_secrets(text), expected)


class TestLogsApiRedaction(ClickhouseTestMixin, APIBaseTest):
    CLASS_DATA_LEVEL_SETUP = True

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        log_item = {
            "uuid": str(uuid4()),
            "team_id": cls.team.id,
            "timestamp": "2026-03-01 10:00:00.000000",
            "observed_timestamp": "2026-03-01 10:00:00.000000",
            "body": f"handled callback {CALLBACK_URL}",
            "severity_text": "info",
            "severity_number": 9,
            "service_name": "api",
            "resource_attributes": {"service.name": "api"},
            "attributes_map_str": {"url.full__str": CALLBACK_URL},
        }
        sync_execute(f"INSERT INTO logs FORMAT JSONEachRow {json.dumps(log_item)}")

    def _headers(self, user_agent: str = MCP_USER_AGENT_MARKER) -> dict[str, str]:
        key = self.create_personal_api_key_with_scopes(["logs:read"])
        return {"authorization": f"Bearer {key}", "user-agent": user_agent}

    def _query(self, user_agent: str):
        return self.client.post(
            f"/api/projects/{self.team.pk}/logs/query",
            {"query": {"dateRange": DATE_RANGE, "serviceNames": ["api"]}},
            format="json",
            headers=self._headers(user_agent),
        )

    # Each log-reading endpoint serves a different payload shape: log rows, attribute values,
    # facet values, and mined pattern examples. A shape the redaction walks past leaks the
    # credential whole.
    @parameterized.expand(
        [
            ("query", "query", {"query": {"dateRange": DATE_RANGE, "serviceNames": ["api"]}}),
            ("attribute_values", "values", {"key": "url.full", "dateRange": json.dumps(DATE_RANGE)}),
            ("facet_values", "facet_values", {"query": {"facetAttribute": "url.full", "dateRange": DATE_RANGE}}),
            ("patterns", "patterns", {"query": {"dateRange": DATE_RANGE, "serviceNames": ["api"]}}),
        ]
    )
    def test_agent_response_holds_no_credential(self, _name, action, payload):
        url = f"/api/projects/{self.team.pk}/logs/{action}"
        headers = self._headers()
        if action == "values":
            response = self.client.get(url, payload, headers=headers)
        else:
            response = self.client.post(url, payload, format="json", headers=headers)

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        body = response.content.decode()
        self.assertIn("[redacted]", body)
        self.assertNotIn(OAUTH_CODE, body)

    def test_mcp_request_keeps_the_rest_of_the_url(self):
        response = self._query(f"cursor/1.0 {MCP_USER_AGENT_MARKER}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        result = response.json()["results"][0]
        self.assertEqual(result["attributes"]["url.full"], REDACTED_CALLBACK_URL)
        self.assertIn(REDACTED_CALLBACK_URL, result["body"])

    def test_direct_api_request_keeps_the_credential(self):
        response = self._query("curl/8.0")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        result = response.json()["results"][0]
        self.assertEqual(result["attributes"]["url.full"], CALLBACK_URL)
