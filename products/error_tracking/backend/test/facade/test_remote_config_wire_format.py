"""Wire-format snapshot tests for the Error tracking remote config facade.

These tests protect the JSON payload that ``build_remote_config_payload``
produces, since it is consumed strictly by PostHog SDKs via the ``/decide``
remote config path. Any drift here is a user-visible regression.

Refactors of the facade's remote config helpers MUST leave these tests
byte-identical.
"""

from __future__ import annotations

import json

from posthog.test.base import BaseTest

from products.error_tracking.backend.facade import build_remote_config_payload
from products.error_tracking.backend.models import ErrorTrackingSuppressionRule


class TestBuildRemoteConfigWireFormat(BaseTest):
    def test_wire_format_empty_rules_autocapture_off(self) -> None:
        self.team.autocapture_exceptions_opt_in = False
        self.team.save()

        payload = build_remote_config_payload(self.team)

        assert payload == {
            "autocaptureExceptions": False,
            "suppressionRules": [],
        }
        # Assert JSON-roundtrip stability — this is the byte format the SDK parses.
        assert json.dumps(payload, sort_keys=True) == '{"autocaptureExceptions": false, "suppressionRules": []}'

    def test_wire_format_autocapture_on(self) -> None:
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()

        payload = build_remote_config_payload(self.team)

        assert payload == {
            "autocaptureExceptions": True,
            "suppressionRules": [],
        }

    def test_wire_format_with_client_safe_rule(self) -> None:
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={
                "type": "AND",
                "values": [
                    {
                        "type": "event",
                        "key": "$exception_type",
                        "operator": "exact",
                        "value": "TypeError",
                    }
                ],
            },
            sampling_rate=1.0,
            order_key=0,
        )

        payload = build_remote_config_payload(self.team)

        assert payload == {
            "autocaptureExceptions": True,
            "suppressionRules": [
                {
                    "type": "AND",
                    "values": [
                        {
                            "type": "event",
                            "key": "$exception_type",
                            "operator": "exact",
                            "value": "TypeError",
                        }
                    ],
                }
            ],
        }

    def test_wire_format_sampling_rate_below_one_emits_samplingRate(self) -> None:
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={
                "type": "AND",
                "values": [
                    {"type": "event", "key": "$exception_type", "operator": "exact", "value": "TypeError"},
                ],
            },
            sampling_rate=0.25,
            order_key=0,
        )

        payload = build_remote_config_payload(self.team)

        assert payload["suppressionRules"][0]["samplingRate"] == 0.25
        # Still has the raw filter keys alongside the samplingRate addition.
        assert payload["suppressionRules"][0]["type"] == "AND"

    def test_wire_format_drops_rules_with_server_only_properties(self) -> None:
        self.team.autocapture_exceptions_opt_in = True
        self.team.save()
        # $exception_sources is a server-only property; rules that reference it must be
        # dropped entirely from the payload so they never reach the client SDK.
        ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters={
                "type": "AND",
                "values": [
                    {"type": "event", "key": "$exception_sources", "operator": "exact", "value": "node_modules"},
                ],
            },
            sampling_rate=1.0,
            order_key=0,
        )

        payload = build_remote_config_payload(self.team)

        assert payload == {
            "autocaptureExceptions": True,
            "suppressionRules": [],
        }
