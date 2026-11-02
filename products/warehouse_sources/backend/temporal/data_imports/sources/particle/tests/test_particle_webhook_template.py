import json

from parameterized import parameterized

from products.cdp.backend.templates.helpers import BaseHogFunctionTemplateTest
from products.warehouse_sources.backend.temporal.data_imports.sources.particle.settings import WEBHOOK_SECRET_HEADER
from products.warehouse_sources.backend.temporal.data_imports.sources.particle.webhook_template import template

WEBHOOK_SECRET = "c2VjcmV0LXNoYXJlZC13aXRoLXBhcnRpY2xl"
SCHEMA_MAPPING = {"events": "schema_events"}
DEVICE_ID = "e00fce68f1d2c3b4a5968778"


class TestParticleWarehouseWebhookTemplate(BaseHogFunctionTemplateTest):
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

    def _query(self, **overrides) -> dict:
        return {
            "event": "env/reading",
            "device_id": DEVICE_ID,
            "published_at": "2026-10-16T09:30:12.512Z",
            "event_id": "01JA6V3M1Q8W5ZK0Y7T2R4N9PB",
            "product_id": "31337",
            "firmware_version": "7",
            **overrides,
        }

    def _request(self, data, query: dict | None = None, headers: dict | None = None, method: str = "POST") -> dict:
        # The webhook sends Particle's own serialization of the event as the body, so `data` is
        # always the published string (or a structured value from a typed publish).
        body = {"name": "env/reading", "data": data, "ttl": 60, "coreid": DEVICE_ID}
        payload = json.dumps(body)
        return {
            "request": {
                "method": method,
                "headers": {WEBHOOK_SECRET_HEADER: WEBHOOK_SECRET} if headers is None else headers,
                "body": json.loads(payload),
                "stringBody": payload,
                "query": self._query() if query is None else query,
            }
        }

    def _inputs(self, **overrides) -> dict:
        return {
            "signing_secret": WEBHOOK_SECRET,
            "schema_mapping": SCHEMA_MAPPING,
            "source_id": "source_test_123",
            **overrides,
        }

    def test_captures_a_json_publish_as_an_event_on_the_device(self):
        self.run_function(self._inputs(), globals=self._request('{"temp": 21.5, "humidity": 40}'))

        assert self.get_mock_posthog_capture_calls() == [
            (
                {
                    "event": "env/reading",
                    "distinct_id": DEVICE_ID,
                    "properties": {
                        "temp": 21.5,
                        "humidity": 40,
                        "$process_person_profile": False,
                        "particle_device_id": DEVICE_ID,
                        "particle_event_id": "01JA6V3M1Q8W5ZK0Y7T2R4N9PB",
                        "particle_published_at": "2026-10-16T09:30:12.512Z",
                        "particle_product_id": "31337",
                        "particle_firmware_version": "7",
                    },
                },
            )
        ]

    @parameterized.expand(
        [
            ("plain_text", "door opened", "door opened"),
            ("json_number", "21.5", 21.5),
            ("json_array", "[1, 2]", [1, 2]),
            ("structured_publish", {"temp": 3}, None),
        ]
    )
    def test_non_object_data_lands_under_a_data_property(self, _name, data, expected):
        self.run_function(self._inputs(), globals=self._request(data))

        properties = self.get_mock_posthog_capture_calls()[0][0]["properties"]
        if expected is None:
            # A typed publish (Device OS 6.2+) delivers an object, which merges like parsed JSON.
            assert properties["temp"] == 3
            assert "data" not in properties
        else:
            assert properties["data"] == expected

    def test_device_data_cannot_overwrite_particle_metadata(self):
        self.run_function(
            self._inputs(),
            globals=self._request('{"particle_device_id": "spoofed", "$process_person_profile": true}'),
        )

        properties = self.get_mock_posthog_capture_calls()[0][0]["properties"]
        assert properties["particle_device_id"] == DEVICE_ID
        assert properties["$process_person_profile"] is False

    def test_sandbox_device_data_cannot_forge_product_metadata(self):
        # Product fields render empty for sandbox devices, so nothing overwrites them after the
        # merge; the reserved keys must be dropped from the device data instead.
        self.run_function(
            self._inputs(),
            globals=self._request(
                '{"particle_product_id": "forged", "particle_firmware_version": "forged", "temp": 1}',
                query=self._query(product_id="", firmware_version=""),
            ),
        )

        properties = self.get_mock_posthog_capture_calls()[0][0]["properties"]
        assert "particle_product_id" not in properties
        assert "particle_firmware_version" not in properties
        assert properties["temp"] == 1

    def test_sandbox_devices_omit_empty_product_fields(self):
        # Product variables render empty for devices outside a product, and an empty string
        # property would read as a real value in breakdowns.
        self.run_function(
            self._inputs(), globals=self._request("1", query=self._query(product_id="", firmware_version=""))
        )

        properties = self.get_mock_posthog_capture_calls()[0][0]["properties"]
        assert "particle_product_id" not in properties
        assert "particle_firmware_version" not in properties

    def test_writes_the_raw_event_to_the_events_table(self):
        self.run_function(self._inputs(), globals=self._request('{"temp": 21.5}'))

        self.mock_produce_to_warehouse_webhooks.assert_called_once_with(
            {
                "event_id": "01JA6V3M1Q8W5ZK0Y7T2R4N9PB",
                "event": "env/reading",
                "data": '{"temp": 21.5}',
                "device_id": DEVICE_ID,
                "product_id": "31337",
                "firmware_version": "7",
                "published_at": "2026-10-16T09:30:12.512Z",
            },
            "schema_events",
        )

    def test_still_captures_when_the_events_table_is_not_mapped(self):
        self.run_function(self._inputs(schema_mapping={}), globals=self._request("1"))

        assert len(self.get_mock_posthog_capture_calls()) == 1
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    @parameterized.expand([("no_device", {"device_id": ""}), ("no_event", {"event": ""})])
    def test_rejects_a_delivery_without_particle_fields(self, _name, overrides):
        res = self.run_function(self._inputs(), globals=self._request("1", query=self._query(**overrides)))

        assert res.result["httpResponse"]["status"] == 400
        assert self.get_mock_posthog_capture_calls() == []
        self.mock_produce_to_warehouse_webhooks.assert_not_called()

    def test_missing_webhook_secret_drops_delivery(self):
        res = self.run_function(self._inputs(signing_secret=""), globals=self._request("1"))

        assert res.result == {
            "httpResponse": {"status": 200, "body": "Webhook secret not configured, delivery dropped"},
            "appMetric": "missing_credential",
        }
        assert self.get_mock_posthog_capture_calls() == []

    @parameterized.expand(
        [
            ("wrong_secret", {WEBHOOK_SECRET_HEADER: "not-the-secret"}),
            ("missing_header", {}),
        ]
    )
    def test_unauthenticated_deliveries_are_rejected(self, _name, headers):
        # Particle signs nothing, so the header set on the webhook is the only proof of origin.
        res = self.run_function(self._inputs(), globals=self._request("1", headers=headers))

        assert res.result == {"httpResponse": {"status": 400, "body": "Bad webhook secret"}}
        assert self.get_mock_posthog_capture_calls() == []

    def test_non_post_is_rejected(self):
        res = self.run_function(self._inputs(), globals=self._request("1", method="GET"))

        assert res.result["httpResponse"]["status"] == 405
        assert self.get_mock_posthog_capture_calls() == []
