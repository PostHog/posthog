from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.attentive import api_client

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
    def test_valid_token(self, mock_session):
        mock_session.return_value.get.return_value = _response(200, {"companyId": "c1"})

        ok, error = api_client.validate_credentials("key")

        assert ok is True
        assert error is None

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_token(self, mock_session):
        mock_session.return_value.get.return_value = _response(401)

        ok, error = api_client.validate_credentials("key")

        assert ok is False
        assert "rejected the API key" in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_falls_back_to_v1_me_on_404(self, mock_session):
        mock_session.return_value.get.side_effect = [_response(404), _response(200)]

        ok, _error = api_client.validate_credentials("key")

        assert ok is True
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert urls == ["https://api.attentivemobile.com/v2/me", "https://api.attentivemobile.com/v1/me"]


class TestCreateWebhook:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_creates_then_disables_until_signing_key_provided(self, mock_session):
        mock_session.return_value.get.return_value = _response(200, {"webhooks": []})
        mock_session.return_value.post.return_value = _response(201, {"id": "wh-1"})
        mock_session.return_value.put.return_value = _response(200, {"id": "wh-1"})

        result = api_client.create_webhook("key", "https://ph.example/webhook", ["sms_sent", "email_opened"])

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        post_body = mock_session.return_value.post.call_args.kwargs["json"]
        assert post_body == {"url": "https://ph.example/webhook", "events": ["sms.sent", "email.opened"]}
        put_body = mock_session.return_value.put.call_args.kwargs["json"]
        assert put_body["disabled"] is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_existing_webhook_short_circuits(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200, {"webhooks": [{"id": "wh-1", "url": "https://ph.example/webhook"}]}
        )

        result = api_client.create_webhook("key", "https://ph.example/webhook", ["sms_sent"])

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]
        mock_session.return_value.post.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_looks_up_id_when_create_response_omits_it(self, mock_session):
        # First GET checks for an existing webhook (none); second GET is the
        # fallback lookup after the create response omits the id.
        mock_session.return_value.get.side_effect = [
            _response(200, {"webhooks": []}),
            _response(200, {"webhooks": [{"id": "wh-9", "url": "https://ph.example/webhook"}]}),
        ]
        mock_session.return_value.post.return_value = _response(201, {})
        mock_session.return_value.put.return_value = _response(200)

        result = api_client.create_webhook("key", "https://ph.example/webhook", ["sms_sent"])

        assert result.success is True
        put_url = mock_session.return_value.put.call_args.args[0]
        assert put_url.endswith("/wh-9")
        assert mock_session.return_value.put.call_args.kwargs["json"]["disabled"] is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fails_when_created_webhook_cannot_be_disabled(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response(200, {"webhooks": []}),
            _response(200, {"webhooks": []}),
        ]
        mock_session.return_value.post.return_value = _response(201, {})

        result = api_client.create_webhook("key", "https://ph.example/webhook", ["sms_sent"])

        assert result.success is False
        assert "could not be disabled" in (result.error or "")
        mock_session.return_value.put.assert_not_called()

    def test_no_mappable_resources_fails(self):
        result = api_client.create_webhook("key", "https://ph.example/webhook", ["unknown_table"])
        assert result.success is False
        assert "None of the selected tables" in (result.error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_http_error_surfaces_friendly_message(self, mock_session):
        mock_session.return_value.get.return_value = _response(200, {"webhooks": []})
        mock_session.return_value.post.return_value = _response(403)

        result = api_client.create_webhook("key", "https://ph.example/webhook", ["sms_sent"])

        assert result.success is False
        assert "denied the request" in (result.error or "")


class TestEnableWebhook:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_enables_matching_webhook(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200, {"webhooks": [{"id": "wh-1", "url": "https://ph.example/webhook", "events": ["sms.sent"]}]}
        )
        mock_session.return_value.put.return_value = _response(200)

        ok, error = api_client.enable_webhook("key", "https://ph.example/webhook")

        assert ok is True
        assert error is None
        put_body = mock_session.return_value.put.call_args.kwargs["json"]
        assert put_body == {"url": "https://ph.example/webhook", "events": ["sms.sent"], "disabled": False}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_missing_webhook_fails(self, mock_session):
        mock_session.return_value.get.return_value = _response(200, {"webhooks": []})

        ok, error = api_client.enable_webhook("key", "https://ph.example/webhook")

        assert ok is False
        assert "No webhook found" in (error or "")


class TestSyncWebhookEvents:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_noop_when_events_already_match(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200, {"webhooks": [{"id": "wh-1", "url": "https://ph.example/webhook", "events": ["sms.sent"]}]}
        )

        result = api_client.sync_webhook_events("key", "https://ph.example/webhook", ["sms_sent"])

        assert result.success is True
        mock_session.return_value.put.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_updates_events_when_drifted(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200, {"webhooks": [{"id": "wh-1", "url": "https://ph.example/webhook", "events": ["sms.sent"]}]}
        )
        mock_session.return_value.put.return_value = _response(200)

        result = api_client.sync_webhook_events("key", "https://ph.example/webhook", ["sms_sent", "email_opened"])

        assert result.success is True
        put_body = mock_session.return_value.put.call_args.kwargs["json"]
        assert put_body == {
            "url": "https://ph.example/webhook",
            "events": ["sms.sent", "email.opened"],
            "disabled": False,
        }

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_preserves_disabled_state_when_drifted(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200,
            {
                "webhooks": [
                    {
                        "id": "wh-1",
                        "url": "https://ph.example/webhook",
                        "events": ["sms.sent"],
                        "disabledAt": "2024-01-01 00:00:00",
                    }
                ]
            },
        )
        mock_session.return_value.put.return_value = _response(200)

        result = api_client.sync_webhook_events("key", "https://ph.example/webhook", ["sms_sent", "email_opened"])

        assert result.success is True
        assert mock_session.return_value.put.call_args.kwargs["json"]["disabled"] is True

    def test_no_mappable_schemas_fails(self):
        result = api_client.sync_webhook_events("key", "https://ph.example/webhook", [])
        assert result.success is False


class TestDeleteWebhook:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_deletes_matching_webhook(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200, {"webhooks": [{"id": "wh-1", "url": "https://ph.example/webhook"}]}
        )
        mock_session.return_value.delete.return_value = _response(204)

        result = api_client.delete_webhook("key", "https://ph.example/webhook")

        assert result.success is True
        delete_url = mock_session.return_value.delete.call_args.args[0]
        assert delete_url == "https://api.attentivemobile.com/v1/webhooks/wh-1"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_missing_webhook_is_success(self, mock_session):
        mock_session.return_value.get.return_value = _response(200, {"webhooks": []})

        assert api_client.delete_webhook("key", "https://ph.example/webhook").success is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_404_on_delete_is_success(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            200, {"webhooks": [{"id": "wh-1", "url": "https://ph.example/webhook"}]}
        )
        delete_resp = mock.MagicMock()
        delete_resp.status_code = 404
        mock_session.return_value.delete.return_value = delete_resp

        assert api_client.delete_webhook("key", "https://ph.example/webhook").success is True


class TestGetExternalWebhookInfo:
    @pytest.mark.parametrize(
        "webhook, expected_status",
        [
            ({"id": "wh-1", "url": "https://ph.example/webhook", "events": ["sms.sent"]}, "enabled"),
            (
                {
                    "id": "wh-1",
                    "url": "https://ph.example/webhook",
                    "events": ["sms.sent"],
                    "disabledAt": "2024-01-01 00:00:00",
                },
                "disabled",
            ),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_reports_status(self, mock_session, webhook, expected_status):
        mock_session.return_value.get.return_value = _response(200, {"webhooks": [webhook]})

        info = api_client.get_external_webhook_info("key", "https://ph.example/webhook")

        assert info.exists is True
        assert info.status == expected_status
        assert info.enabled_events == ["sms.sent"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_missing_webhook(self, mock_session):
        mock_session.return_value.get.return_value = _response(200, {"webhooks": []})

        info = api_client.get_external_webhook_info("key", "https://ph.example/webhook")

        assert info.exists is False
        assert info.error is None
