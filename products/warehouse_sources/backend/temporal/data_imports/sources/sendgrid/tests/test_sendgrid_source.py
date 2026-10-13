from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendgrid import (
    SendGridSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import SENDGRID_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source import SendGridSource

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.source"
_TRANSPORT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid"

ALL_ENDPOINTS = {
    "bounces",
    "blocks",
    "invalid_emails",
    "spam_reports",
    "global_unsubscribes",
    "stats",
    "unsubscribe_groups",
    "marketing_lists",
    "templates",
    "message_activity",
}


def _config() -> SendGridSourceConfig:
    return SendGridSourceConfig(api_key="SG.test-key")


class TestSendGridSource:
    @pytest.mark.parametrize(
        ("status", "schema_name", "expected_ok", "expected_has_msg"),
        [
            (200, None, True, False),
            (200, "bounces", True, False),
            (401, None, False, True),
            (401, "bounces", False, True),
            # 403 = valid token, missing scope: accepted at source-create, rejected per-schema.
            (403, None, True, False),
            (403, "bounces", False, True),
            (None, None, False, True),
        ],
    )
    def test_validate_credentials(
        self, status: int | None, schema_name: str | None, expected_ok: bool, expected_has_msg: bool
    ) -> None:
        # A named schema probes its own endpoint; source-create probes `/scopes`.
        with (
            patch(f"{_SOURCE_MODULE}.get_status_code", return_value=status),
            patch(f"{_SOURCE_MODULE}.get_endpoint_status_code", return_value=status),
        ):
            ok, msg = SendGridSource().validate_credentials(_config(), team_id=1, schema_name=schema_name)
        assert ok is expected_ok
        assert (msg is not None) is expected_has_msg

    @pytest.mark.parametrize(
        ("gated_endpoint", "scope"),
        [
            ("marketing_lists", "marketing.read"),
            # The add-on gate must stay per-table: a 403 on message_activity cannot make the
            # picker (or a sync) treat any other table as unreachable.
            ("message_activity", "email_activity.read"),
        ],
    )
    def test_get_endpoint_permissions_flags_only_the_unreadable_table(self, gated_endpoint: str, scope: str) -> None:
        # The bug this guards: with no per-table probe every table looked reachable, so a key without
        # the scope still got the gated table enabled, and the first sync hard-failed.
        def status_for(_api_key: str, config: Any) -> int:
            return 403 if config.name == gated_endpoint else 200

        with patch(f"{_TRANSPORT_MODULE}.get_endpoint_status_code", side_effect=status_for):
            permissions = SendGridSource().get_endpoint_permissions(_config(), team_id=1, endpoints=list(ALL_ENDPOINTS))

        gated_reason = permissions[gated_endpoint]
        assert gated_reason is not None
        assert scope in gated_reason
        assert {name: reason for name, reason in permissions.items() if reason is not None} == {
            gated_endpoint: gated_reason
        }

    @pytest.mark.parametrize("name", sorted(ALL_ENDPOINTS))
    def test_every_endpoint_declares_a_scope_to_name(self, name: str) -> None:
        # An endpoint added without one would render "missing the `` scope" at users.
        assert SENDGRID_ENDPOINTS[name].required_scope
