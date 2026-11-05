from collections import Counter
from datetime import timedelta
from io import StringIO
from typing import Any

from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase
from django.utils import timezone

import requests
from parameterized import parameterized
from structlog.testing import capture_logs

from posthog.integrations import IntegrationManager, IntegrationReference
from posthog.models.team import Team

from products.warehouse_sources.backend.facade.contracts import (
    CONNECTION_FIELDS_STRIPPED_KEY,
    DEAD_CREDENTIALS_CLEARED_KEY,
)
from products.warehouse_sources.backend.logic.source_credentials_cleanup import cleanup_dead_credentials
from products.warehouse_sources.backend.logic.source_credentials_rollout import reset_caches
from products.warehouse_sources.backend.logic.source_credentials_sync import _process_batch
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.source_inputs_backup import ExternalDataSourceInputsBackup
from products.warehouse_sources.backend.temporal.data_imports.sources.common.legacy_oauth import (
    LegacyOAuthGrant,
    LegacyOAuthGrantUnusable,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.tests.management.test_source_credentials_commands import POSTGRES_INPUTS
from products.warehouse_sources.backend.tests.management.test_strip_source_credentials_commands import _StripTestCase
from products.warehouse_sources.sources.hubspot.auth import HubspotRetryableError, hubspot_exchange_legacy_grant
from products.warehouse_sources.sources.hubspot.source import HubspotSource

COMMAND = "cleanup_dead_warehouse_source_credentials"
FAKE_TOKEN = "fake-cleanup-token-never-print-12345"
LEGACY_INPUTS = {"hubspot_secret_key": FAKE_TOKEN, "hubspot_refresh_token": FAKE_TOKEN, "custom_properties": "keep"}
MISSING_ID = "2147483647"


class TestCleanupDeadSourceCredentials(_StripTestCase):
    @parameterized.expand(
        [
            ("legacy", "Hubspot", LEGACY_INPUTS, None, {"custom_properties": "keep"}),
            ("top_level", "Hubspot", {"hubspot_integration_id": MISSING_ID}, MISSING_ID, {}),
            (
                "nested",
                "Stripe",
                {
                    "auth_method": {"selection": "oauth", "stripe_integration_id": MISSING_ID},
                    "stripe_account_id": "acct",
                },
                MISSING_ID,
                {"auth_method": {"selection": "oauth"}, "stripe_account_id": "acct"},
            ),
            ("typed_in", "Postgres", POSTGRES_INPUTS, MISSING_ID, POSTGRES_INPUTS),
            ("invalid_column", "Postgres", POSTGRES_INPUTS, "invalid-reference", POSTGRES_INPUTS),
            (
                "uuid_column",
                "Postgres",
                POSTGRES_INPUTS,
                "00000000-0000-0000-0000-000000000001",
                POSTGRES_INPUTS,
            ),
            (
                "stale_pointer",
                "Stripe",
                {
                    "auth_method": {
                        "selection": "api_key",
                        "stripe_integration_id": MISSING_ID,
                        "stripe_secret_key": FAKE_TOKEN,
                    }
                },
                MISSING_ID,
                {"auth_method": {"selection": "api_key", "stripe_secret_key": FAKE_TOKEN}},
            ),
        ]
    )
    def test_cleanup_backs_up_clears_and_verifies(
        self, _name: str, source_type: str, inputs: dict[str, Any], column: str | None, kept: dict[str, Any]
    ) -> None:
        source = self._source(inputs, source_type=source_type, column=column)
        updated_at = source.updated_at

        with (
            patch.object(HubspotSource, "adopt_legacy_oauth", side_effect=LegacyOAuthGrantUnusable),
            capture_logs() as logs,
        ):
            output = self._run(COMMAND, "--execute")

        assert "cleaned=1" in output
        assert FAKE_TOKEN not in output
        assert FAKE_TOKEN not in str(logs)
        stored = self._stored(source)
        assert stored == {**kept, DEAD_CREDENTIALS_CLEARED_KEY: stored[DEAD_CREDENTIALS_CLEARED_KEY]}
        assert self._reference(source) is None
        source.refresh_from_db()
        assert source.updated_at == updated_at
        backup = ExternalDataSourceInputsBackup.objects.for_team(self.team.pk).get(source_id=source.id)
        assert backup.inputs == inputs
        assert backup.source_type == source_type
        assert "skipped_cleaned=1" in self._run("backfill_warehouse_source_credentials", "--execute")
        assert self._rows() == []
        assert "dangling=0 mismatched=0" in self._run("reconcile_warehouse_source_credentials", "--verify")

        with patch.object(HubspotSource, "adopt_legacy_oauth") as adopt:
            assert "already_cleaned=1" in self._run(COMMAND, "--execute")
        adopt.assert_not_called()
        backup.refresh_from_db()
        assert backup.inputs == inputs
        assert self._stored(source) == stored

        assert "restored_from_backup=1" in self._run(
            "restore_warehouse_source_connection_fields", "--source-id", str(source.id)
        )
        assert self._stored(source) == stored
        assert "restored_from_backup=1" in self._run(
            "restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id)
        )
        assert self._stored(source) == inputs

    @parameterized.expand([("default", ()), ("explicit", ("--dry-run",))])
    def test_preview_never_writes_or_checks_tokens(self, _name: str, args: tuple[str, ...]) -> None:
        legacy = self._source(LEGACY_INPUTS, source_type="Hubspot")
        dangling_inputs = {"hubspot_integration_id": MISSING_ID}
        dangling = self._source(dangling_inputs, source_type="Hubspot", column=MISSING_ID)

        with patch.object(HubspotSource, "adopt_legacy_oauth") as adopt:
            output = self._run(COMMAND, *args)

        adopt.assert_not_called()
        assert "would_check_legacy_tokens=1" in output
        assert "would_clean=1" in output
        assert self._stored(legacy) == LEGACY_INPUTS
        assert self._stored(dangling) == dangling_inputs
        assert self._reference(dangling) == MISSING_ID
        assert self._backups() == []

    @parameterized.expand(
        [
            ("recent", True, ExternalDataSchema.Status.COMPLETED, 1, "skipped_recent_sync"),
            ("running_enabled", True, ExternalDataSchema.Status.RUNNING, 60, "skipped_running"),
            ("running_disabled", False, ExternalDataSchema.Status.RUNNING, 60, "skipped_running"),
            ("old", True, ExternalDataSchema.Status.COMPLETED, 60, "cleaned"),
            ("disabled_recent", False, ExternalDataSchema.Status.COMPLETED, 1, "cleaned"),
            ("custom_window", True, ExternalDataSchema.Status.COMPLETED, 10, "cleaned", 7),
        ]
    )
    def test_schema_activity_controls_cleanup(
        self, _name: str, should_sync: bool, status: str, age: int, outcome: str, idle_days: int = 30
    ) -> None:
        source = self._source(LEGACY_INPUTS, source_type="Hubspot")
        schema = ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="contacts",
            should_sync=should_sync,
            status=status,
            last_synced_at=timezone.now() - timedelta(days=age),
        )

        with patch.object(HubspotSource, "adopt_legacy_oauth", side_effect=LegacyOAuthGrantUnusable) as adopt:
            output = self._run(COMMAND, "--execute", "--idle-days", str(idle_days))

        assert f"{outcome}=1" in output
        if outcome != "cleaned":
            adopt.assert_not_called()
            assert self._stored(source) == LEGACY_INPUTS
            assert self._backups() == []
        schema.refresh_from_db()
        assert schema.should_sync == should_sync
        assert schema.status == status

    @parameterized.expand(
        [
            ("usable", None, "skipped_legacy_usable"),
            ("transient", Exception(FAKE_TOKEN), "skipped_transient"),
            ("timeout", TimeoutError(FAKE_TOKEN), "skipped_transient"),
        ]
    )
    def test_only_an_unusable_grant_allows_cleanup(self, _name: str, error: Exception | None, outcome: str) -> None:
        source = self._source(LEGACY_INPUTS, source_type="Hubspot")
        grant = LegacyOAuthGrant(
            kind="hubspot",
            external_id="fake-account",
            config={},
            sensitive_config={"refresh_token": FAKE_TOKEN},
            pointer_key="hubspot_integration_id",
            legacy_keys=HubspotSource().legacy_oauth_keys(),
            refresh_token=FAKE_TOKEN,
        )
        with (
            patch.object(HubspotSource, "adopt_legacy_oauth", return_value=grant, side_effect=error),
            capture_logs() as logs,
        ):
            output = self._run(COMMAND, "--execute")

        assert f"{outcome}=1" in output
        assert self._stored(source) == LEGACY_INPUTS
        assert self._backups() == []
        assert FAKE_TOKEN not in output
        assert FAKE_TOKEN not in str(logs)

    @parameterized.expand(["inputs", "column", "running", "recent", "deleted"])
    def test_changes_during_token_check_prevent_cleanup(self, change: str) -> None:
        source = self._source(LEGACY_INPUTS, source_type="Hubspot")

        def check_tokens(inputs: dict[str, Any]) -> None:
            if change == "inputs":
                SourceInputsStore.update_oauth_inputs(source, {"hubspot_refresh_token": "fake-new-token"})
            elif change == "column":
                self._link(source, MISSING_ID)
            elif change == "deleted":
                ExternalDataSource.objects.filter(team_id=self.team.pk, id=source.id).update(deleted=True)
            else:
                ExternalDataSchema.objects.create(
                    team=self.team,
                    source=source,
                    name="contacts",
                    status=ExternalDataSchema.Status.RUNNING
                    if change == "running"
                    else ExternalDataSchema.Status.COMPLETED,
                    last_synced_at=timezone.now(),
                )
            raise LegacyOAuthGrantUnusable

        with patch.object(HubspotSource, "adopt_legacy_oauth", side_effect=check_tokens):
            output = self._run(COMMAND, "--execute")

        expected = {"running": "skipped_running", "recent": "skipped_recent_sync", "deleted": "skipped_gone"}
        assert f"{expected.get(change, 'skipped_changed')}=1" in output
        assert DEAD_CREDENTIALS_CLEARED_KEY not in self._stored(source)
        assert self._backups() == []

    @parameterized.expand(["oauth", "typed_in", "surviving_pointer", "surviving_column", "stripped"])
    def test_live_references_and_stripped_sources_stay_unchanged(self, kind: str) -> None:
        if kind == "typed_in":
            source = self._backfilled_source()
        else:
            row = IntegrationManager.hubspot.oauth.create(self.team.pk, external_id="fake-account", config={})
            pointer = MISSING_ID if kind == "surviving_column" else str(row.id)
            column = MISSING_ID if kind == "surviving_pointer" else str(row.id)
            inputs: dict[str, Any] = {"hubspot_integration_id": pointer}
            if kind == "stripped":
                inputs = {CONNECTION_FIELDS_STRIPPED_KEY: timezone.now().isoformat()}
            source = self._source(inputs, source_type="Hubspot", column=column)
        before = self._stored(source)
        reference = self._reference(source)

        with patch.object(HubspotSource, "adopt_legacy_oauth") as adopt:
            output = self._run(COMMAND, "--execute")

        adopt.assert_not_called()
        outcome = (
            "skipped_stripped"
            if kind == "stripped"
            else ("skipped_existing_credentials" if kind.startswith("surviving") else "skipped_no_dead_credentials")
        )
        assert f"{outcome}=1" in output
        assert self._stored(source) == before
        assert self._reference(source) == reference
        assert self._backups() == []

    def test_marker_is_hidden_preserved_and_cannot_be_set_by_inputs(self) -> None:
        source = self._source(POSTGRES_INPUTS, column=MISSING_ID)
        self._run(COMMAND, "--execute")
        source.refresh_from_db()
        marker = self._stored(source)[DEAD_CREDENTIALS_CLEARED_KEY]

        assert DEAD_CREDENTIALS_CLEARED_KEY not in SourceInputsStore.load(source)
        assert DEAD_CREDENTIALS_CLEARED_KEY not in SourceInputsStore.load_settings(source)
        assert DEAD_CREDENTIALS_CLEARED_KEY not in SourceInputsStore.load_many([source])[source.id]
        self.enabled_flags.clear()
        reset_caches()
        SourceInputsStore.save(source, {**SourceInputsStore.load(source), DEAD_CREDENTIALS_CLEARED_KEY: "forged"})
        assert self._stored(source)[DEAD_CREDENTIALS_CLEARED_KEY] == marker
        with self.assertRaises(ValueError):
            SourceInputsStore.update_runtime(source, {DEAD_CREDENTIALS_CLEARED_KEY: "forged"})
        with self.assertRaises(ValueError):
            SourceInputsStore.update_runtime(source, remove=[DEAD_CREDENTIALS_CLEARED_KEY])

        other = self._source()
        SourceInputsStore.save(other, {**POSTGRES_INPUTS, DEAD_CREDENTIALS_CLEARED_KEY: "forged"})
        assert DEAD_CREDENTIALS_CLEARED_KEY not in self._stored(other)

    @parameterized.expand(["Postgres", "Hubspot"])
    def test_backfill_rechecks_sources_cleaned_after_batch_read(self, source_type: str) -> None:
        inputs = LEGACY_INPUTS if source_type == "Hubspot" else POSTGRES_INPUTS
        source = self._source(inputs, source_type=source_type, column=MISSING_ID)
        with patch.object(HubspotSource, "adopt_legacy_oauth", side_effect=LegacyOAuthGrantUnusable):
            self._run(COMMAND, "--execute")

        counts: Counter[tuple[str, str]] = Counter()
        with patch.object(HubspotSource, "adopt_legacy_oauth") as adopt:
            _process_batch([source], True, counts)

        adopt.assert_not_called()
        assert counts == Counter({(source_type, "skipped_cleaned"): 1})
        assert self._reference(source) is None
        assert self._rows() == []

    def test_backfill_links_a_cleaned_source_after_a_reconnect(self) -> None:
        source = self._source({"hubspot_integration_id": MISSING_ID}, source_type="Hubspot", column=MISSING_ID)
        self._run(COMMAND, "--execute")
        row = IntegrationManager.hubspot.oauth.create(self.team.pk, external_id="fake-account", config={})
        fresh = ExternalDataSource.objects.get(pk=source.pk)
        SourceInputsStore.save(fresh, {**SourceInputsStore.load(fresh), "hubspot_integration_id": row.id})
        # The dual write was off, so the reconnect left the column empty.
        ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id=None)
        assert DEAD_CREDENTIALS_CLEARED_KEY in self._stored(source)

        counts: Counter[tuple[str, str]] = Counter()
        _process_batch([ExternalDataSource.objects.get(pk=source.pk)], True, counts)

        assert counts == Counter({("Hubspot", "oauth_linked"): 1})
        assert self._reference(source) == str(IntegrationReference.from_legacy_id(row.id))

    def test_restore_after_cleanup_keeps_later_settings_and_runtime_state(self) -> None:
        inputs = {
            "auth_method": {"selection": "oauth", "stripe_integration_id": MISSING_ID},
            "stripe_account_id": "acct",
        }
        source = self._source(inputs, source_type="Stripe", column=MISSING_ID)
        self._run(COMMAND, "--execute")
        fresh = ExternalDataSource.objects.get(pk=source.pk)
        SourceInputsStore.update_runtime(fresh, {"cdc_position": "later"})

        assert "restored_from_backup=1" in self._run(
            "restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id)
        )

        assert self._stored(source) == {**inputs, "cdc_position": "later"}

    @parameterized.expand([("unmarked", False, "not_stripped"), ("marked", True, "no_row_and_no_backup")])
    def test_restore_without_cleanup_backup(self, _name: str, marked: bool, outcome: str) -> None:
        inputs = {DEAD_CREDENTIALS_CLEARED_KEY: timezone.now().isoformat()} if marked else {}
        source = self._source(inputs)
        output = StringIO()
        if marked:
            with self.assertRaises(CommandError):
                call_command(
                    "restore_warehouse_source_connection_fields",
                    "--execute",
                    "--source-id",
                    str(source.id),
                    stdout=output,
                )
        else:
            call_command(
                "restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id), stdout=output
            )
        assert f"{outcome}=1" in output.getvalue()
        assert self._stored(source) == inputs

    @parameterized.expand([("--batch-size", "0"), ("--limit", "-1"), ("--idle-days", "0")])
    def test_invalid_options_fail(self, option: str, value: str) -> None:
        with self.assertRaises(CommandError):
            self._run(COMMAND, option, value)

    def test_failures_report_counts_without_exception_values(self) -> None:
        source = self._source(LEGACY_INPUTS, source_type="Hubspot")
        output = StringIO()
        with (
            patch.object(HubspotSource, "has_legacy_oauth_tokens", side_effect=Exception(FAKE_TOKEN)),
            capture_logs() as logs,
        ):
            with self.assertRaises(CommandError):
                call_command(COMMAND, "--execute", stdout=output)
        assert "failed=1" in output.getvalue()
        assert FAKE_TOKEN not in output.getvalue()
        assert FAKE_TOKEN not in str(logs)
        assert self._stored(source) == LEGACY_INPUTS
        assert self._backups() == []

    def test_limit_zero_skips_every_source(self) -> None:
        source = self._source(LEGACY_INPUTS, source_type="Hubspot")
        with patch.object(HubspotSource, "adopt_legacy_oauth") as adopt:
            assert cleanup_dead_credentials(execute=True, limit=0) == Counter()
        adopt.assert_not_called()
        assert self._stored(source) == LEGACY_INPUTS

    def test_another_teams_row_does_not_keep_dead_credentials_alive(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        row = IntegrationManager.hubspot.oauth.create(other_team.pk, external_id="fake-account", config={})
        inputs = {"hubspot_integration_id": str(row.id)}
        source = self._source(inputs, source_type="Hubspot", column=str(row.id))

        assert "cleaned=1" in self._run(COMMAND, "--execute")

        assert self._reference(source) is None
        assert "hubspot_integration_id" not in self._stored(source)
        assert row.id in IntegrationManager.any.get_many(other_team.pk, [row.id])

    def test_cleanup_replaces_an_old_backup_and_clears_a_stale_column_on_a_marked_source(self) -> None:
        inputs = {**POSTGRES_INPUTS, DEAD_CREDENTIALS_CLEARED_KEY: "2026-01-01T00:00:00+00:00"}
        source = self._source(inputs, column=MISSING_ID)
        ExternalDataSourceInputsBackup.objects.for_team(self.team.pk).create(
            team_id=self.team.pk, source_id=source.id, source_type="Postgres", inputs={"password": "fake-old"}
        )

        assert "cleaned=1" in self._run(COMMAND, "--execute")

        backup = ExternalDataSourceInputsBackup.objects.for_team(self.team.pk).get(source_id=source.id)
        assert backup.inputs == inputs
        assert self._reference(source) is None
        assert "dangling=0 mismatched=0" in self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_command_filters_teams_and_types_across_batches(self) -> None:
        other_team = Team.objects.create(organization=self.organization)
        included = [
            self._source({"hubspot_integration_id": MISSING_ID}, source_type="Hubspot", team=team)
            for team in (self.team, other_team)
        ]
        excluded = self._source(POSTGRES_INPUTS, column=MISSING_ID)

        output = self._run(
            COMMAND,
            "--execute",
            "--team-id",
            str(self.team.pk),
            "--team-id",
            str(other_team.pk),
            "--source-type",
            "Hubspot",
            "--batch-size",
            "1",
            "--limit",
            "2",
        )

        assert "cleaned=2" in output
        assert all(DEAD_CREDENTIALS_CLEARED_KEY in self._stored(source) for source in included)
        assert self._stored(excluded) == POSTGRES_INPUTS
        assert self._reference(excluded) == MISSING_ID


class TestLegacyGrantFailures(SimpleTestCase):
    @parameterized.expand(
        [
            ("refresh_timeout", False, requests.ReadTimeout(FAKE_TOKEN)),
            ("refresh_rate_limit", False, ScriptedResponse(status=429, json={"message": "retry"})),
            ("refresh_server_error", False, ScriptedResponse(status=503, json={"message": "retry"})),
            ("refresh_request_timeout", False, ScriptedResponse(status=408, json={"message": "retry"})),
            ("refresh_unknown_4xx", False, ScriptedResponse(status=477, json={"message": "retry"})),
            ("refresh_malformed_body", False, ScriptedResponse(json=[])),
            (
                "refresh_client_rejected",
                False,
                ScriptedResponse(status=400, json={"error": "invalid_client", "status": "BAD_CLIENT_ID"}),
            ),
            ("info_timeout", True, requests.ReadTimeout(FAKE_TOKEN)),
            ("info_rate_limit", True, ScriptedResponse(status=429)),
            ("info_server_error", True, ScriptedResponse(status=503)),
            ("info_request_timeout", True, ScriptedResponse(status=408)),
            ("info_unknown_4xx", True, ScriptedResponse(status=477)),
            ("info_malformed_body", True, ScriptedResponse(json=[])),
        ]
    )
    def test_transport_failures_do_not_mark_a_grant_unusable(
        self, _name: str, info_request: bool, response: ScriptedResponse | Exception
    ) -> None:
        refreshed = ScriptedResponse(json={"access_token": FAKE_TOKEN, "refresh_token": FAKE_TOKEN})
        failing = always(response)

        def script(request: RecordedRequest) -> ScriptedResponse:
            if info_request and "access-tokens" not in request.url:
                return refreshed
            return failing(request)

        with (
            patch(
                "products.warehouse_sources.sources.hubspot.auth.credentials_service.get_secrets",
                return_value={"HUBSPOT_APP_CLIENT_ID": "fake-id", "HUBSPOT_APP_CLIENT_SECRET": "fake-secret"},
            ),
            scripted_network(script),
            self.assertRaises(HubspotRetryableError) as raised,
        ):
            hubspot_exchange_legacy_grant(FAKE_TOKEN)
        assert FAKE_TOKEN not in str(raised.exception)

    @parameterized.expand(
        [
            ("rfc_6749", {"error": "invalid_grant", "error_description": "refresh token is invalid"}),
            ("legacy_status", {"status": "BAD_REFRESH_TOKEN", "message": "refresh token is invalid"}),
        ]
    )
    def test_only_a_rejected_refresh_token_marks_a_grant_unusable(self, _name: str, body: dict[str, str]) -> None:
        with (
            patch(
                "products.warehouse_sources.sources.hubspot.auth.credentials_service.get_secrets",
                return_value={"HUBSPOT_APP_CLIENT_ID": "fake-id", "HUBSPOT_APP_CLIENT_SECRET": "fake-secret"},
            ),
            scripted_network(always(ScriptedResponse(status=400, json=body))),
            self.assertRaises(LegacyOAuthGrantUnusable),
        ):
            hubspot_exchange_legacy_grant(FAKE_TOKEN)
