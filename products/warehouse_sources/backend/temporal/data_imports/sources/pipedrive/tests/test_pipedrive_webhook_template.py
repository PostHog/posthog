import json
import base64
from typing import Any

from parameterized import parameterized

from posthog.cdp.templates.helpers import BaseHogFunctionTemplateTest

from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.webhook_template import template

SOURCE_ID = "source_test_123"
AUTH_USER = "posthog"
AUTH_PASSWORD = "s3cr3t-token-value"
SCHEMA_MAPPING = {"deal": "schema_deals", "person": "schema_persons", "activity": "schema_activities"}


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class TestPipedriveWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
    template = template

    def createHogGlobals(self, globals=None) -> dict:
        data: dict = {
            "request": {
                "method": "POST",
                "headers": {},
                "body": {},
                "query": {},
                "stringBody": "",
                "ip": "127.0.0.1",
            },
        }
        if globals and globals.get("request"):
            data["request"].update(globals["request"])
        return data

    def _payload(self, entity: str = "deal", action: str = "create", version: str = "2.0") -> dict[str, Any]:
        return {
            "meta": {
                "action": action,
                "entity": entity,
                "version": version,
                "entity_id": "42",
                "timestamp": "2026-05-01T10:00:00.000Z",
                "company_id": "1",
                "user_id": "2",
            },
            "data": {"id": 42, "title": "Renewal"},
            "previous": {},
        }

    def _request(self, body: dict, *, headers: dict[str, str] | None = None, method: str = "POST") -> dict:
        payload = json.dumps(body)
        return {
            "request": {
                "method": method,
                "headers": {"authorization": _basic(AUTH_USER, AUTH_PASSWORD)} if headers is None else headers,
                "body": json.loads(payload),
                "stringBody": payload,
                "query": {},
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "http_auth_user": AUTH_USER,
            "http_auth_password": AUTH_PASSWORD,
            "bypass_auth_check": False,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": SOURCE_ID,
            **overrides,
        }

    @parameterized.expand(
        [
            ("deal", "schema_deals"),
            ("person", "schema_persons"),
            ("activity", "schema_activities"),
        ]
    )
    def test_routes_each_entity_to_its_table(self, entity: str, expected_schema_id: str) -> None:
        globals = self._request(self._payload(entity=entity))

        self.run_function(self._inputs(), globals=globals)

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(globals["request"]["body"], expected_schema_id)

    @parameterized.expand(
        [
            ("wrong_password", {"authorization": _basic(AUTH_USER, "not-the-password")}, {}, 401),
            ("wrong_user", {"authorization": _basic("someone-else", AUTH_PASSWORD)}, {}, 401),
            ("missing_header", {}, {}, 401),
            ("no_credentials_configured", {"authorization": "Basic x"}, {"http_auth_password": ""}, 400),
        ]
    )
    def test_unverified_delivery_is_rejected(
        self, _name: str, headers: dict[str, str], input_overrides: dict[str, Any], expected_status: int
    ) -> None:
        globals = self._request(self._payload(), headers=headers)

        res = self.run_function(self._inputs(**input_overrides), globals=globals)

        assert res.result["httpResponse"]["status"] == expected_status
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_delete_event_is_acknowledged_and_dropped(self) -> None:
        globals = self._request(self._payload(action="delete"))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_v1_payload_is_rejected(self) -> None:
        globals = self._request(self._payload(version="1.0"))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 400
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_entity_without_a_selected_table_is_acknowledged_and_dropped(self) -> None:
        # The subscription is a wildcard, so entities the user never selected arrive on every
        # account. A non-2xx here would put the webhook into Pipedrive's retry and ban path.
        globals = self._request(self._payload(entity="note"))

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result["httpResponse"]["status"] == 200
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_non_post_request_returns_405(self) -> None:
        globals = self._request(self._payload(), method="GET")

        res = self.run_function(self._inputs(), globals=globals)

        assert res.result == {"httpResponse": {"status": 405, "body": "Method not allowed"}}
        self.mock_produce_to_warehouse_webhooks.assert_not_called()
