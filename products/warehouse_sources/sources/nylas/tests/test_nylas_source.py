from typing import Any

import pytest

from products.warehouse_sources.sources.nylas._config import NylasSourceConfig
from products.warehouse_sources.sources.nylas.source import NylasSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, always, scripted_network

WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/0190aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee"
TRIGGERS = [
    "message.created",
    "message.updated",
    "event.created",
    "event.updated",
    "event.deleted",
    "contact.updated",
]

# Verbatim Nylas error for a webhook URL that did not answer the challenge.
CHALLENGE_FAILED = {
    "request_id": "1b2f7e6c-3a55-4d0c-9d2e-6b8d0b1f1c11",
    "error": {"type": "70005", "message": "unable.verify.webhook_url : status is not ok, got 404"},
}


def _source() -> NylasSource:
    return NylasSource()


def _config(**overrides: Any) -> NylasSourceConfig:
    return NylasSourceConfig(api_key="nyk_test", **overrides)


def _webhook(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "wh-1",
        "description": "PostHog data warehouse",
        "trigger_types": TRIGGERS,
        "webhook_url": WEBHOOK_URL,
        "status": "active",
        **overrides,
    }


def _list(*webhooks: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json={"request_id": "r", "data": list(webhooks)})


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "valid", "message"),
        [
            (200, True, None),
            (401, False, "Nylas rejected the API key"),
            (400, False, "Nylas rejected the API key"),
            (503, False, "Couldn't reach Nylas"),
        ],
    )
    def test_maps_the_probe_status_to_a_message(self, status: int, valid: bool, message: str | None) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={"data": []}))) as network:
            is_valid, error = _source().validate_credentials(_config(region="eu"), team_id=1)

        assert is_valid is valid
        assert (error is None) if message is None else (error is not None and message in error)
        assert network.requests_log[0].url == "https://api.eu.nylas.com/v3/grants?limit=1"
        assert network.requests_log[0].headers["authorization"] == "Bearer nyk_test"


class TestWebhookManagement:
    def test_create_registers_the_message_triggers_and_keeps_the_returned_secret(self) -> None:
        script = [_list(), ScriptedResponse(json={"data": _webhook(webhook_secret="whsec-from-create")})]
        with scripted_network(script) as network:
            result = _source().create_webhook(_config(), WEBHOOK_URL, team_id=1)

        assert result.success is True
        assert result.extra_inputs == {"signing_secret": "whsec-from-create"}
        assert result.pending_inputs == []
        create = network.requests_log[1]
        assert (create.method, create.path) == ("POST", "/v3/webhooks")
        assert create.json() == {
            "trigger_types": TRIGGERS,
            "webhook_url": WEBHOOK_URL,
            "description": "PostHog data warehouse",
        }

    def test_create_reuses_a_webhook_left_by_an_earlier_attempt_and_rotates_its_secret(self) -> None:
        # The list endpoint never returns the secret, so a second webhook for the same URL
        # would deliver every notification twice.
        script = [
            _list(_webhook(trigger_types=["message.created"], status="failed")),
            ScriptedResponse(json={"data": _webhook()}),
            ScriptedResponse(json={"data": _webhook(webhook_secret="whsec-rotated")}),
        ]
        with scripted_network(script) as network:
            result = _source().create_webhook(_config(), WEBHOOK_URL, team_id=1)

        assert result.extra_inputs == {"signing_secret": "whsec-rotated"}
        assert [(request.method, request.path) for request in network.requests_log] == [
            ("GET", "/v3/webhooks"),
            ("PUT", "/v3/webhooks/wh-1"),
            ("POST", "/v3/webhooks/rotate-secret/wh-1"),
        ]
        assert network.requests_log[1].json() == {"trigger_types": TRIGGERS, "status": "active"}

    def test_create_reports_the_nylas_error_when_the_challenge_fails(self) -> None:
        with scripted_network([_list(), ScriptedResponse(status=400, json=CHALLENGE_FAILED)]):
            result = _source().create_webhook(_config(), WEBHOOK_URL, team_id=1)

        assert result.success is False
        assert result.error == "unable.verify.webhook_url : status is not ok, got 404"

    def test_create_asks_for_the_secret_when_nylas_returns_none(self) -> None:
        with scripted_network([_list(), ScriptedResponse(json={"data": _webhook()})]):
            result = _source().create_webhook(_config(), WEBHOOK_URL, team_id=1)

        assert result.success is True
        assert result.pending_inputs == ["signing_secret"]

    @pytest.mark.parametrize(
        ("current", "expects_update"),
        [(TRIGGERS, False), (["message.created", "grant.expired"], True)],
    )
    def test_sync_updates_the_triggers_only_when_they_drifted(self, current: list[str], expects_update: bool) -> None:
        script = [_list(_webhook(trigger_types=current)), ScriptedResponse(json={"data": _webhook()})]
        with scripted_network(script) as network:
            result = _source().sync_webhook_events(_config(), WEBHOOK_URL, 1, ["messages"])

        assert result.success is True
        methods = [request.method for request in network.requests_log]
        assert methods == (["GET", "PUT"] if expects_update else ["GET"])
        if expects_update:
            assert network.requests_log[1].json() == {"trigger_types": TRIGGERS}

    def test_sync_fails_when_the_webhook_is_gone(self) -> None:
        with scripted_network([_list(_webhook(webhook_url="https://example.com/other"))]):
            result = _source().sync_webhook_events(_config(), WEBHOOK_URL, 1, ["messages"])

        assert result.success is False

    def test_info_reports_the_matching_webhook(self) -> None:
        other = _webhook(id="wh-2", webhook_url="https://example.com/other")
        with scripted_network([_list(other, _webhook(status="failing"))]):
            info = _source().get_external_webhook_info(_config(), WEBHOOK_URL, team_id=1)

        assert info is not None
        assert (info.exists, info.url, info.status, info.enabled_events) == (True, WEBHOOK_URL, "failing", TRIGGERS)

    @pytest.mark.parametrize(
        ("script", "expected_methods", "success"),
        [
            ([_list(_webhook()), ScriptedResponse(json={"data": {"status": "success"}})], ["GET", "DELETE"], True),
            ([_list(_webhook()), ScriptedResponse(status=404, json={})], ["GET", "DELETE"], True),
            ([_list()], ["GET"], True),
            ([ScriptedResponse(status=401, json={"error": {"message": "Invalid API Key"}})], ["GET"], False),
        ],
    )
    def test_delete_removes_the_matching_webhook(
        self, script: list[ScriptedResponse], expected_methods: list[str], success: bool
    ) -> None:
        with scripted_network(script) as network:
            result = _source().delete_webhook(_config(), WEBHOOK_URL, team_id=1)

        assert result.success is success
        assert [request.method for request in network.requests_log] == expected_methods
