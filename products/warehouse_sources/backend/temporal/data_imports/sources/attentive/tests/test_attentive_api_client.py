from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.attentive import api_client
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.attentive.api_client"


def _response(status_code: int = 200, body: Any = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body if body is not None else {}
    if status_code >= 400:
        error = requests.HTTPError(response=resp)
        resp.raise_for_status.side_effect = error
    else:
        resp.raise_for_status.return_value = None
    return resp


URL = "https://ph.example/webhook"
WEBHOOKS = "/v1/webhooks"


class TestEventsForResources:
    def test_maps_resources_to_event_types(self):
        events = api_client._events_for_resources(["sms_sent", "email_opened"])
        assert events == ["sms.sent", "email.opened"]

    def test_unknown_resources_are_skipped(self):
        assert api_client._events_for_resources(["nope", "sms_sent"]) == ["sms.sent"]

    def test_duplicates_collapse(self):
        assert api_client._events_for_resources(["sms_sent", "sms_sent"]) == ["sms.sent"]


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_token(self, mock_session):
        mock_session.return_value.get.return_value = _response(401)

        ok, error = api_client.validate_credentials("key")

        assert ok is False
        assert "rejected your API key" in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_falls_back_to_v1_me_on_404(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(404), _response(200)]

        ok, _error = api_client.validate_credentials("key")

        assert ok is True
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == ["https://api.attentivemobile.com/v2/me", "https://api.attentivemobile.com/v1/me"]


class TestCreateWebhook:
    def test_creates_then_disables_until_signing_key_provided(self):
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": []}),
                ScriptedResponse(status=201, json={"id": "wh-1"}),
                ScriptedResponse(json={"id": "wh-1"}),
            ]
        ) as network:
            result = api_client.create_webhook("key", URL, ["sms_sent", "email_opened"])

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        get, post, put = network.requests_log
        assert [r.method for r in network.requests_log] == ["GET", "POST", "PUT"]
        assert get.headers["authorization"] == "Bearer key"
        assert post.json() == {"url": URL, "events": ["sms.sent", "email.opened"]}
        assert put.path == f"{WEBHOOKS}/wh-1"
        assert put.json()["disabled"] is True

    def test_existing_webhook_short_circuits(self):
        with scripted_network([ScriptedResponse(json={"webhooks": [{"id": "wh-1", "url": URL}]})]) as network:
            result = api_client.create_webhook("key", URL, ["sms_sent"])

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        assert [r.method for r in network.requests_log] == ["GET"]

    def test_looks_up_id_when_create_response_omits_it(self):
        # First GET checks for an existing webhook (none); second GET is the
        # fallback lookup after the create response omits the id.
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": []}),
                ScriptedResponse(status=201, json={}),
                ScriptedResponse(json={"webhooks": [{"id": "wh-9", "url": URL}]}),
                ScriptedResponse(),
            ]
        ) as network:
            result = api_client.create_webhook("key", URL, ["sms_sent"])

        assert result.success is True
        put = network.requests_log[-1]
        assert put.method == "PUT"
        assert put.path.endswith("/wh-9")
        assert put.json()["disabled"] is True

    def test_fails_when_created_webhook_cannot_be_disabled(self):
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": []}),
                ScriptedResponse(status=201, json={}),
                ScriptedResponse(json={"webhooks": []}),
            ]
        ) as network:
            result = api_client.create_webhook("key", URL, ["sms_sent"])

        assert result.success is False
        assert "could not be disabled" in (result.error or "")
        assert "PUT" not in [r.method for r in network.requests_log]

    def test_no_mappable_resources_fails(self):
        result = api_client.create_webhook("key", URL, ["unknown_table"])
        assert result.success is False
        assert "None of the selected tables" in (result.error or "")

    def test_http_error_surfaces_friendly_message(self):
        with scripted_network([ScriptedResponse(json={"webhooks": []}), ScriptedResponse(status=403)]):
            result = api_client.create_webhook("key", URL, ["sms_sent"])

        assert result.success is False
        assert "Webhooks permission" in (result.error or "")


class TestEnableWebhook:
    def test_enables_matching_webhook(self):
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": [{"id": "wh-1", "url": URL, "events": ["sms.sent"]}]}),
                ScriptedResponse(),
            ]
        ) as network:
            ok, error = api_client.enable_webhook("key", URL)

        assert ok is True
        assert error is None
        put = network.requests_log[-1]
        assert put.method == "PUT"
        assert put.json() == {"url": URL, "events": ["sms.sent"], "disabled": False}

    def test_missing_webhook_fails(self):
        with scripted_network([ScriptedResponse(json={"webhooks": []})]):
            ok, error = api_client.enable_webhook("key", URL)

        assert ok is False
        assert "No webhook found" in (error or "")


class TestSyncWebhookEvents:
    def test_noop_when_events_already_match(self):
        with scripted_network(
            [ScriptedResponse(json={"webhooks": [{"id": "wh-1", "url": URL, "events": ["sms.sent"]}]})]
        ) as network:
            result = api_client.sync_webhook_events("key", URL, ["sms_sent"])

        assert result.success is True
        assert [r.method for r in network.requests_log] == ["GET"]

    def test_updates_events_when_drifted(self):
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": [{"id": "wh-1", "url": URL, "events": ["sms.sent"]}]}),
                ScriptedResponse(),
            ]
        ) as network:
            result = api_client.sync_webhook_events("key", URL, ["sms_sent", "email_opened"])

        assert result.success is True
        assert network.requests_log[-1].json() == {
            "url": URL,
            "events": ["sms.sent", "email.opened"],
            "disabled": False,
        }

    def test_preserves_disabled_state_when_drifted(self):
        webhook = {"id": "wh-1", "url": URL, "events": ["sms.sent"], "disabledAt": "2024-01-01 00:00:00"}
        with scripted_network([ScriptedResponse(json={"webhooks": [webhook]}), ScriptedResponse()]) as network:
            result = api_client.sync_webhook_events("key", URL, ["sms_sent", "email_opened"])

        assert result.success is True
        assert network.requests_log[-1].json()["disabled"] is True

    def test_no_mappable_schemas_fails(self):
        result = api_client.sync_webhook_events("key", URL, [])
        assert result.success is False


class TestDeleteWebhook:
    def test_deletes_matching_webhook(self):
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": [{"id": "wh-1", "url": URL}]}),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = api_client.delete_webhook("key", URL)

        assert result.success is True
        delete = network.requests_log[-1]
        assert delete.method == "DELETE"
        assert delete.url == "https://api.attentivemobile.com/v1/webhooks/wh-1"

    def test_missing_webhook_is_success(self):
        with scripted_network([ScriptedResponse(json={"webhooks": []})]):
            assert api_client.delete_webhook("key", URL).success is True

    def test_404_on_delete_is_success(self):
        with scripted_network(
            [
                ScriptedResponse(json={"webhooks": [{"id": "wh-1", "url": URL}]}),
                ScriptedResponse(status=404),
            ]
        ):
            assert api_client.delete_webhook("key", URL).success is True


class TestGetExternalWebhookInfo:
    @pytest.mark.parametrize(
        "webhook, expected_status",
        [
            ({"id": "wh-1", "url": URL, "events": ["sms.sent"]}, "enabled"),
            (
                {"id": "wh-1", "url": URL, "events": ["sms.sent"], "disabledAt": "2024-01-01 00:00:00"},
                "disabled",
            ),
        ],
    )
    def test_reports_status(self, webhook, expected_status):
        with scripted_network([ScriptedResponse(json={"webhooks": [webhook]})]):
            info = api_client.get_external_webhook_info("key", URL)

        assert info.exists is True
        assert info.status == expected_status
        assert info.enabled_events == ["sms.sent"]

    def test_missing_webhook(self):
        with scripted_network([ScriptedResponse(json={"webhooks": []})]):
            info = api_client.get_external_webhook_info("key", URL)

        assert info.exists is False
        assert info.error is None
