import time
from typing import Any

from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import override_settings

from parameterized import parameterized

from posthog.integrations import IntegrationManager, IntegrationReference

from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.tests.management.test_source_credentials_commands import (
    _CredentialsCommandTestCase,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.warehouse_sources.sources.hubspot.auth import HubspotLegacyGrant, hubspot_refresh_access_token
from products.warehouse_sources.sources.sdk import LegacyOAuthGrantUnusable

EXCHANGE = "products.warehouse_sources.sources.hubspot.source.hubspot_exchange_legacy_grant"
LEGACY_INPUTS: dict[str, Any] = {"hubspot_secret_key": "fake-access", "hubspot_refresh_token": "fake-refresh"}
HUB_ID = "424242"


def _grant(**overrides: Any) -> HubspotLegacyGrant:
    values: dict[str, Any] = {
        "external_id": HUB_ID,
        "config": {
            "hub_id": int(HUB_ID),
            "hub_domain": "example.com",
            "user": "user@example.com",
            "user_id": 1,
            "scopes": ["oauth"],
            "expires_in": 1800,
        },
        "access_token": "fake-new-access",
        "refresh_token": "fake-refresh",
    }
    return HubspotLegacyGrant(**{**values, **overrides})


class TestHubspotLegacyAdoption(_CredentialsCommandTestCase):
    def _legacy_source(self, **kwargs: Any) -> ExternalDataSource:
        return self._source(dict(LEGACY_INPUTS), source_type=ExternalDataSourceType.HUBSPOT, **kwargs)

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk))

    def _hubspot_rows(self) -> list[Any]:
        return IntegrationManager.hubspot.oauth.list(self.team.pk)

    def _adopt(self, *args: str) -> str:
        return self._run("backfill_warehouse_source_credentials", "--source-type", "Hubspot", "--execute", *args)

    @parameterized.expand([("new_row", False), ("existing_row_for_the_same_hub", True)])
    def test_legacy_source_moves_into_a_hubspot_row(self, _name: str, row_exists: bool) -> None:
        existing = None
        if row_exists:
            existing = IntegrationManager.hubspot.oauth.create(
                self.team.pk,
                external_id=HUB_ID,
                config={"hub_id": int(HUB_ID)},
                sensitive_config={"access_token": "fake-other", "refresh_token": "fake-other-refresh"},
            )
        source = self._legacy_source()

        with patch(EXCHANGE, return_value=_grant()):
            output = self._adopt()

        assert "hubspot_legacy_adopted=1" in output
        rows = self._hubspot_rows()
        assert len(rows) == 1
        row = rows[0]
        if existing is not None:
            assert row.id == existing.id
            assert row.refresh_token == "fake-other-refresh"
        else:
            assert row.integration_id == HUB_ID
            assert row.access_token == "fake-new-access"
            assert row.refresh_token == "fake-refresh"
            assert row.config["hub_domain"] == "example.com"
            assert row.config["expires_in"] == 1800
            assert abs(row.config["refreshed_at"] - time.time()) < 60
        assert self._stored(source) == {"hubspot_integration_id": str(row.id)}
        assert self._reference(source) == str(IntegrationReference.from_legacy_id(row.id))
        assert "fake-" not in output

    def test_preview_writes_nothing_and_calls_no_network(self) -> None:
        source = self._legacy_source()

        with patch(EXCHANGE) as exchange:
            output = self._run("backfill_warehouse_source_credentials", "--source-type", "Hubspot")

        assert "hubspot_legacy_adopted=1" in output
        exchange.assert_not_called()
        assert self._hubspot_rows() == []
        assert self._stored(source) == LEGACY_INPUTS
        assert self._reference(source) is None

    def test_second_run_changes_nothing(self) -> None:
        source = self._legacy_source()
        with patch(EXCHANGE, return_value=_grant()) as exchange:
            self._adopt()
            stored = self._stored(source)
            output = self._adopt()

        assert exchange.call_count == 1
        assert "hubspot_legacy_adopted" not in output
        assert "unchanged=1" in output
        assert self._stored(source) == stored
        assert len(self._hubspot_rows()) == 1

    @parameterized.expand(
        [
            ("token_rejected", LegacyOAuthGrantUnusable("rejected")),
            ("hubspot_unreachable", LegacyOAuthGrantUnusable("unreachable")),
        ]
    )
    def test_unusable_token_is_skipped_and_counted(self, _name: str, error: Exception) -> None:
        source = self._legacy_source()

        with patch(EXCHANGE, side_effect=error):
            output = self._adopt()

        assert "skipped_legacy_token_unusable=1" in output
        assert self._hubspot_rows() == []
        assert self._stored(source) == LEGACY_INPUTS
        assert self._reference(source) is None

    def test_refresh_token_changed_during_the_exchange_is_skipped(self) -> None:
        source = self._legacy_source()

        with patch(EXCHANGE, return_value=_grant(refresh_token="fake-rotated")):
            # The grant holds the token that the inputs had when the exchange ran.
            with patch.object(
                SourceInputsStore,
                "load_stored",
                side_effect=[
                    dict(LEGACY_INPUTS),
                    dict(LEGACY_INPUTS),
                    {**LEGACY_INPUTS, "hubspot_refresh_token": "fake-changed"},
                ],
            ):
                output = self._adopt()

        assert "skipped_legacy_token_unusable=1" in output
        assert self._hubspot_rows() == []
        assert self._stored(source) == LEGACY_INPUTS

    @parameterized.expand(
        [
            ("pointer_only", {"hubspot_integration_id": "7"}),
            ("pointer_and_leftover_token", {"hubspot_integration_id": "7", "hubspot_refresh_token": "fake-refresh"}),
        ]
    )
    def test_modern_source_is_not_exchanged(self, _name: str, inputs: dict[str, Any]) -> None:
        source = self._source(inputs, source_type=ExternalDataSourceType.HUBSPOT)

        with patch(EXCHANGE) as exchange:
            self._adopt()

        exchange.assert_not_called()
        assert self._hubspot_rows() == []
        assert self._stored(source) == inputs

    def test_verify_reports_a_legacy_source_until_it_moves(self) -> None:
        self._legacy_source()

        with self.assertRaises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--verify", "--source-type", "Hubspot")

        with patch(EXCHANGE, return_value=_grant()):
            self._adopt()

        output = self._run("reconcile_warehouse_source_credentials", "--verify", "--source-type", "Hubspot")
        assert "Verified" in output

    def test_converted_source_refreshes_through_its_integration(self) -> None:
        source = self._legacy_source()
        with patch(EXCHANGE, return_value=_grant()):
            self._adopt()
        row = self._hubspot_rows()[0]
        IntegrationManager.hubspot.oauth.update(
            self.team.pk, row.id, config_patch={"refreshed_at": int(time.time()) - 100000}
        )
        response = MagicMock(status_code=200)
        response.json.return_value = {"access_token": "fake-refreshed", "expires_in": 1800}

        with (
            override_settings(HUBSPOT_APP_CLIENT_ID="fake-id", HUBSPOT_APP_CLIENT_SECRET="fake-secret"),
            patch("posthog.models.integration.oauth.requests.post", return_value=response) as post,
        ):
            refreshed = IntegrationManager.hubspot.oauth.refresh_access_token(self.team.pk, row.id)

        assert post.call_args.kwargs["data"]["refresh_token"] == "fake-refresh"
        assert refreshed.access_token == "fake-refreshed"
        assert self._stored(source) == {"hubspot_integration_id": str(row.id)}

    def test_stale_legacy_write_after_conversion_does_not_restore_the_keys(self) -> None:
        source = self._legacy_source()
        with patch(EXCHANGE, return_value=_grant()):
            self._adopt()
        converted = self._stored(source)
        response = MagicMock(status_code=200)
        response.json.return_value = {"access_token": "fake-late"}
        session = MagicMock()
        session.post.return_value = response

        with (
            patch("products.warehouse_sources.sources.hubspot.auth.make_tracked_session", return_value=session),
            patch(
                "products.warehouse_sources.sources.hubspot.auth._hubspot_app_credentials",
                return_value={"client_id": "fake-id", "client_secret": "fake-secret"},
            ),
        ):
            hubspot_refresh_access_token("fake-refresh", source_id=str(source.id))

        assert self._stored(source) == converted
        assert self._reference(source) == str(
            IntegrationReference.from_legacy_id(int(converted["hubspot_integration_id"]))
        )
