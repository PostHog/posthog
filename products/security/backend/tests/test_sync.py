from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import jwt as pyjwt
import requests
from parameterized import parameterized

from products.security.backend.logic.snapshot import (
    current_snapshot,
    last_synced_at,
    reset_memo,
    stored_version,
    write_snapshot,
)
from products.security.backend.logic.sync import InvalidSnapshot, sync_access_rules

RULE = {
    "id": "r1",
    "targetType": "email",
    "targetValue": "x@example.com",
    "effect": "block",
    "scope": "signup",
    "expiresAt": None,
}
GENERATED_AT = "2026-09-17T12:00:00Z"
HUB = {
    "SECURITY_HUB_URL": "https://hub.example.com/",
    "SECURITY_HUB_REGION": "us",
    "SECURITY_HUB_OUTBOUND_JWT_SECRETS": ["out-us"],
}


def _response(status: int, body: object = None) -> MagicMock:
    response = MagicMock(status_code=status)
    response.json.return_value = body
    response.raise_for_status.side_effect = None if status < 400 else requests.HTTPError(str(status), response=response)
    return response


@override_settings(**HUB)
class TestSync(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_memo()

    @patch("products.security.backend.logic.sync.requests.get")
    def test_first_pull_stores_rules_and_sends_a_region_token(self, get: MagicMock) -> None:
        get.return_value = _response(
            200, {"version": "v1", "region": "us", "rules": [RULE], "generatedAt": GENERATED_AT}
        )
        result = sync_access_rules()
        assert (result.status, result.rule_count) == ("updated", 1)
        assert stored_version() == "v1"
        assert last_synced_at() is not None
        assert current_snapshot().rule_count == 1

        (url,), kwargs = get.call_args
        assert url == "https://hub.example.com/webhooks/access-rules/snapshot"
        assert kwargs["params"] == {"region": "us"}
        assert kwargs["timeout"] == 10
        assert "If-None-Match" not in kwargs["headers"]
        token = kwargs["headers"]["Authorization"].removeprefix("Bearer ")
        claims = pyjwt.decode(token, "out-us", algorithms=["HS256"], audience="posthog:security_hub:rules")
        assert claims["op"] == "rules:read"

    @patch("products.security.backend.logic.sync.requests.get")
    def test_a_write_older_than_the_stored_generated_at_reports_stale_not_updated(self, get: MagicMock) -> None:
        write_snapshot("v-current", [RULE], generated_at_ms=10**15)
        # The dropped fetch has a different rule count than the stored write, so a bug that
        # forwards the rejected count instead of None would show up as a value, not a coincidence.
        get.return_value = _response(
            200,
            {
                "version": "v-late",
                "region": "us",
                "rules": [RULE, {**RULE, "id": "r2"}],
                "generatedAt": GENERATED_AT,
            },
        )
        result = sync_access_rules()
        assert (result.status, result.rule_count) == ("stale", None)
        assert stored_version() == "v-current"
        # The hub still answered, so contact with it counts as successful.
        assert last_synced_at() is not None

    @patch("products.security.backend.logic.sync.requests.get")
    def test_unchanged_snapshot_sends_the_etag_and_keeps_rules(self, get: MagicMock) -> None:
        get.return_value = _response(
            200, {"version": "v1", "region": "us", "rules": [RULE], "generatedAt": GENERATED_AT}
        )
        sync_access_rules()
        get.return_value = _response(304)
        assert sync_access_rules().status == "unchanged"
        assert get.call_args.kwargs["headers"]["If-None-Match"] == '"v1"'
        assert stored_version() == "v1"

    @parameterized.expand(
        [
            ("wrong region", {"version": "v2", "region": "eu", "rules": []}),
            ("no rules list", {"version": "v2", "region": "us", "rules": "x"}),
            ("no version", {"region": "us", "rules": []}),
            ("no generatedAt", {"version": "v2", "region": "us", "rules": []}),
            ("unparseable generatedAt", {"version": "v2", "region": "us", "rules": [], "generatedAt": "not-a-date"}),
            (
                "naive generatedAt",
                {"version": "v2", "region": "us", "rules": [], "generatedAt": "2026-09-17T12:00:00"},
            ),
        ]
    )
    @patch("products.security.backend.logic.sync.requests.get")
    def test_bad_bodies_raise_and_keep_the_stored_snapshot(self, _name: str, body: dict, get: MagicMock) -> None:
        get.return_value = _response(
            200, {"version": "v1", "region": "us", "rules": [RULE], "generatedAt": GENERATED_AT}
        )
        sync_access_rules()
        get.return_value = _response(200, body)
        with self.assertRaises(InvalidSnapshot):
            sync_access_rules()
        assert stored_version() == "v1"

    @patch("products.security.backend.logic.sync.requests.get")
    def test_hub_errors_raise_and_keep_the_stored_snapshot(self, get: MagicMock) -> None:
        get.return_value = _response(
            200, {"version": "v1", "region": "us", "rules": [RULE], "generatedAt": GENERATED_AT}
        )
        sync_access_rules()
        get.return_value = _response(503)
        with self.assertRaises(requests.HTTPError):
            sync_access_rules()
        get.side_effect = requests.ConnectionError("down")
        with self.assertRaises(requests.ConnectionError):
            sync_access_rules()
        get.side_effect = None
        non_json = _response(200)
        non_json.json.side_effect = requests.exceptions.JSONDecodeError("bad json", "", 0)
        get.return_value = non_json
        with self.assertRaises(requests.exceptions.JSONDecodeError):
            sync_access_rules()
        assert stored_version() == "v1"

    @parameterized.expand(
        [
            ("no url", {"SECURITY_HUB_URL": ""}),
            ("purpose disabled", {"SECURITY_HUB_OUTBOUND_JWT_SECRETS": []}),
        ]
    )
    @patch("products.security.backend.logic.sync.requests.get")
    def test_not_configured_does_nothing(self, _name: str, overrides: dict, get: MagicMock) -> None:
        with override_settings(**overrides):
            assert sync_access_rules().status == "not_configured"
        get.assert_not_called()

    @parameterized.expand(
        [
            ("https in production", "https://hub.example.com/", False, False, "updated"),
            ("http localhost under debug", "http://localhost:1234/", True, False, "updated"),
            ("http localhost under test", "http://localhost:1234/", False, True, "updated"),
            ("http in production", "http://hub.example.com/", False, False, "not_configured"),
            ("http localhost outside debug or test", "http://localhost:1234/", False, False, "not_configured"),
        ]
    )
    @patch("products.security.backend.logic.sync.requests.get")
    @patch("products.security.backend.logic.sync.mint_rules_token")
    def test_hub_url_scheme_is_validated(
        self, _name: str, url: str, debug: bool, test_flag: bool, expected: str, mint: MagicMock, get: MagicMock
    ) -> None:
        get.return_value = _response(
            200, {"version": "v1", "region": "us", "rules": [RULE], "generatedAt": GENERATED_AT}
        )
        mint.return_value = "token"
        with override_settings(SECURITY_HUB_URL=url, DEBUG=debug, TEST=test_flag):
            assert sync_access_rules().status == expected
        if expected == "not_configured":
            mint.assert_not_called()
            get.assert_not_called()
