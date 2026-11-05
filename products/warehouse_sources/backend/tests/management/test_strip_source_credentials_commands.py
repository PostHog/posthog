from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any, cast

import pytest
import time_machine
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.integration import ANY, Integration

from products.warehouse_sources.backend.facade.contracts import CONNECTION_FIELDS_STRIPPED_KEY
from products.warehouse_sources.backend.logic.source_credentials import WarehouseSourceCredentialsStore
from products.warehouse_sources.backend.logic.source_credentials_rollout import DUAL_WRITE_FLAG, READ_FLAG, reset_caches
from products.warehouse_sources.backend.logic.source_credentials_sync import SKIPPED_STRIPPED, _process_batch
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.source_inputs_backup import ExternalDataSourceInputsBackup
from products.warehouse_sources.backend.temporal.data_imports import schema_flags
from products.warehouse_sources.backend.tests.management.test_source_credentials_commands import (
    POSTGRES_CONNECTION,
    POSTGRES_INPUTS,
    _CredentialsCommandTestCase,
)

POSTGRES_SETTINGS = {"schema": "public"}


class _StripTestCase(_CredentialsCommandTestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_caches()
        self.addCleanup(reset_caches)
        flags = patch.object(
            schema_flags.posthoganalytics,
            "feature_enabled",
            side_effect=lambda flag, *args, **kwargs: flag in self.enabled_flags,
        )
        flags.start()
        self.addCleanup(flags.stop)
        self.enabled_flags: set[str] = {DUAL_WRITE_FLAG, READ_FLAG}

    def _backfilled_source(self, **kwargs: Any) -> ExternalDataSource:
        source = self._source(**kwargs)
        self._link(source, self._row_for(source, POSTGRES_CONNECTION))
        return ExternalDataSource.objects.get(pk=source.pk)

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk))

    def _row(self, source: ExternalDataSource) -> dict[str, Any] | None:
        return WarehouseSourceCredentialsStore.get(ExternalDataSource.objects.get(pk=source.pk))

    def _set_row(self, source: ExternalDataSource, fields: dict[str, Any]) -> None:
        WarehouseSourceCredentialsStore.update(ExternalDataSource.objects.get(pk=source.pk), fields)

    def _delete_row(self, source: ExternalDataSource) -> None:
        Integration.objects._with_auth(ANY).filter(id=int(self._reference(source) or 0)).delete()

    def _backups(self) -> list[ExternalDataSourceInputsBackup]:
        return list(ExternalDataSourceInputsBackup.objects.unscoped().all())


class TestStripWarehouseSourceConnectionFields(_StripTestCase):
    @parameterized.expand([("default", ()), ("explicit", ("--dry-run",))])
    def test_dry_run_writes_nothing(self, _name: str, args: tuple[str, ...]) -> None:
        source = self._backfilled_source()

        output = self._run("strip_warehouse_source_connection_fields", *args)

        assert "Dry run" in output
        assert "would_strip=1" in output
        assert self._stored(source) == POSTGRES_INPUTS
        assert self._backups() == []

    def test_execute_backs_up_then_strips_and_reads_still_return_every_field(self) -> None:
        source = self._backfilled_source()

        output = self._run("strip_warehouse_source_connection_fields", "--execute")

        assert "stripped=1" in output
        assert "fake-password-value" not in output
        stored = self._stored(source)
        assert set(stored) == {*POSTGRES_SETTINGS, CONNECTION_FIELDS_STRIPPED_KEY}
        assert self._reference(source) is not None
        backup = ExternalDataSourceInputsBackup.objects.for_team(self.team.pk).get(source_id=source.id)
        assert backup.inputs == POSTGRES_INPUTS
        assert backup.source_type == "Postgres"
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == POSTGRES_INPUTS

    @parameterized.expand(
        [
            ("read_flag_off", lambda case, source: case.enabled_flags.discard(READ_FLAG), "skipped_read_flag_off"),
            (
                "dual_write_flag_off",
                lambda case, source: case.enabled_flags.discard(DUAL_WRITE_FLAG),
                "skipped_read_flag_off",
            ),
            ("missing_row", lambda case, source: case._delete_row(source), "skipped_missing_row"),
            (
                "unreadable_row",
                lambda case, source: (
                    Integration.objects._with_auth(ANY)
                    .filter(id=int(case._reference(source) or 0))
                    .update(sensitive_config={})
                ),
                "skipped_unreadable_row",
            ),
            (
                "row_differs",
                lambda case, source: case._set_row(source, {**POSTGRES_CONNECTION, "password": "fake-other"}),
                "skipped_row_differs",
            ),
            (
                "no_reference",
                lambda case, source: ExternalDataSource.objects.filter(pk=source.pk).update(
                    credentials_integration_id=None
                ),
                "skipped_no_reference",
            ),
        ]
    )
    def test_a_source_that_fails_a_check_is_not_stripped(
        self, _name: str, break_check: Callable[[Any, ExternalDataSource], Any], expected_outcome: str
    ) -> None:
        source = self._backfilled_source()
        break_check(self, source)
        before = self._stored(source)

        output = self._run("strip_warehouse_source_connection_fields", "--execute")

        assert f"{expected_outcome}=1" in output
        assert self._stored(source) == before
        assert self._backups() == []

    @parameterized.expand(
        [
            # (name, source type, inputs, column, outcome, stored inputs after the run)
            (
                "top_level",
                "Hubspot",
                {"hubspot_integration_id": "7"},
                "7",
                "stripped",
                {},
            ),
            (
                "nested",
                "Stripe",
                {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}, "stripe_account_id": "acct"},
                "7",
                "stripped",
                {"auth_method": {"selection": "oauth"}, "stripe_account_id": "acct"},
            ),
            (
                "slack_hidden_key",
                "Slack",
                {"slack_integration_id": "7"},
                "7",
                "stripped",
                {},
            ),
            ("no_reference", "Hubspot", {"hubspot_integration_id": "7"}, None, "skipped_no_reference", None),
            ("reference_differs", "Hubspot", {"hubspot_integration_id": "7"}, "8", "skipped_reference_differs", None),
            ("no_pointer_in_use", "Hubspot", {}, "7", "skipped_no_row_needed", None),
            (
                "unreadable_shape",
                "Stripe",
                {"auth_method": "oauth", "stripe_integration_id": "7"},
                "7",
                "skipped_unreadable_shape",
                None,
            ),
        ]
    )
    def test_an_oauth_source_is_stripped_only_when_the_column_holds_its_in_use_pointer(
        self,
        _name: str,
        source_type: str,
        inputs: dict[str, Any],
        column: str | None,
        expected_outcome: str,
        stripped: dict[str, Any] | None,
    ) -> None:
        source = self._source(inputs, source_type=source_type, column=column)

        output = self._run("strip_warehouse_source_connection_fields", "--execute")

        assert f"{expected_outcome}=1" in output
        if stripped is None:
            assert self._stored(source) == inputs
            assert self._backups() == []
            return
        assert self._stored(source) == {
            **stripped,
            CONNECTION_FIELDS_STRIPPED_KEY: self._stored(source)[CONNECTION_FIELDS_STRIPPED_KEY],
        }
        [backup] = self._backups()
        assert backup.inputs == inputs
        # A read puts the column value back, as an int, at the path of the in-use OAuth field.
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == _with_int_pointers(inputs)

    @parameterized.expand(
        [("from_column", None, "restored_from_row"), ("prefer_backup", "--prefer-backup", "restored_from_backup")]
    )
    def test_restore_of_an_oauth_source_puts_its_pointer_back(
        self, _name: str, flag: str | None, expected_outcome: str
    ) -> None:
        inputs = {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}, "stripe_account_id": "acct"}
        source = self._source(inputs, source_type="Stripe", column="7")
        self._run("strip_warehouse_source_connection_fields", "--execute")

        output = self._run(
            "restore_warehouse_source_connection_fields",
            "--execute",
            "--source-id",
            str(source.id),
            *([flag] if flag else []),
        )

        assert f"{expected_outcome}=1" in output
        assert self._stored(source) == inputs
        assert self._reference(source) == "7"

    def test_restore_of_an_oauth_source_without_a_column_uses_the_backup(self) -> None:
        source = self._source({"hubspot_integration_id": "7"}, source_type="Hubspot", column="7")
        self._run("strip_warehouse_source_connection_fields", "--execute")
        ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id=None)

        output = self._run("restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id))

        assert "restored_from_backup=1" in output
        assert self._stored(source) == {"hubspot_integration_id": "7"}
        assert self._reference(source) == "7"

    @parameterized.expand(
        [("from_row", None, "restored_from_row"), ("from_backup", "--prefer-backup", "restored_from_backup")]
    )
    def test_a_slack_token_source_stays_typed_in_through_strip_and_restore(
        self, _name: str, flag: str | None, expected_outcome: str
    ) -> None:
        # Without the token, Slack would pick its legacy OAuth pointer and read the row reference as one.
        inputs = {"slack_access_token": "xoxb-fake"}
        source = self._source(inputs, source_type="Slack")
        reference = self._row_for(source, inputs)
        self._link(source, reference)

        output = self._run("strip_warehouse_source_connection_fields", "--execute")

        assert "stripped=1" in output
        assert "slack_access_token" not in self._stored(source)
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == inputs

        output = self._run(
            "restore_warehouse_source_connection_fields",
            "--execute",
            "--source-id",
            str(source.id),
            *([flag] if flag else []),
        )

        assert f"{expected_outcome}=1" in output
        assert self._stored(source) == inputs
        assert self._reference(source) == reference

    def test_a_strip_after_a_restore_replaces_the_backup(self) -> None:
        source = self._backfilled_source()
        first_strip = datetime(2026, 1, 1, tzinfo=UTC)
        with time_machine.travel(first_strip, tick=False):
            self._run("strip_warehouse_source_connection_fields", "--execute")
        assert "already_stripped=1" in self._run("strip_warehouse_source_connection_fields", "--execute")
        assert [backup.created_at for backup in self._backups()] == [first_strip]

        self._run("restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id))
        reloaded = ExternalDataSource.objects.get(pk=source.pk)
        SourceInputsStore.save(reloaded, {**SourceInputsStore.load(reloaded), "password": "fake-rotated"})
        second_strip = first_strip + timedelta(days=24)
        with time_machine.travel(second_strip, tick=False):
            assert "stripped=1" in self._run("strip_warehouse_source_connection_fields", "--execute")

        [backup] = self._backups()
        assert backup.inputs == {**POSTGRES_INPUTS, "password": "fake-rotated"}
        assert backup.created_at == second_strip

    def test_a_leaf_with_an_extra_encryption_layer_still_strips(self) -> None:
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
        source = self._backfilled_source()
        ExternalDataSource.objects.filter(pk=source.pk).update(
            job_inputs={**POSTGRES_INPUTS, "password": field.encrypt(POSTGRES_INPUTS["password"])}
        )

        output = self._run("strip_warehouse_source_connection_fields", "--execute")

        assert "stripped=1" in output
        assert set(self._stored(source)) == {*POSTGRES_SETTINGS, CONNECTION_FIELDS_STRIPPED_KEY}

    @patch("products.warehouse_sources.backend.models.external_data_source.capture_exception", create=True)
    def test_soft_delete_of_a_stripped_source_whose_row_is_gone_records_no_error(self, capture: Any) -> None:
        source = self._backfilled_source()
        self._run("strip_warehouse_source_connection_fields", "--execute")
        self._delete_row(source)

        ExternalDataSource.objects.get(pk=source.pk).soft_delete()

        assert ExternalDataSource.objects.get(pk=source.pk).deleted is True
        capture.assert_not_called()

    def test_backfill_never_overwrites_the_row_of_a_stripped_source(self) -> None:
        source = self._backfilled_source()
        self._run("strip_warehouse_source_connection_fields", "--execute")

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_stripped=1" in output
        assert self._row(source) == POSTGRES_CONNECTION

        self._delete_row(source)
        with pytest.raises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_backfill_rechecks_a_source_stripped_after_its_batch_was_read(self) -> None:
        source = self._backfilled_source()
        stale = ExternalDataSource.objects.get(pk=source.pk)
        self._run("strip_warehouse_source_connection_fields", "--execute")
        rotated = {**POSTGRES_CONNECTION, "password": "fake-rotated"}
        self._set_row(source, rotated)

        counts: Counter[tuple[str, str]] = Counter()
        _process_batch([stale], True, counts)

        assert counts == Counter({("Postgres", SKIPPED_STRIPPED): 1})
        assert self._row(source) == rotated


class TestRestoreWarehouseSourceConnectionFields(_StripTestCase):
    def _stripped_source(self) -> ExternalDataSource:
        source = self._backfilled_source()
        self._run("strip_warehouse_source_connection_fields", "--execute")
        return source

    @parameterized.expand(
        [
            # The row holds a credential changed after the strip, which the restore must keep.
            (
                "from_row",
                lambda case, source: case._set_row(source, {**POSTGRES_CONNECTION, "password": "fake-rotated"}),
                (),
                "restored_from_row",
                "fake-rotated",
            ),
            (
                "missing_row",
                lambda case, source: case._delete_row(source),
                (),
                "restored_from_backup",
                "fake-password-value",
            ),
            (
                "prefer_backup",
                lambda case, source: case._set_row(source, {}),
                ("--prefer-backup",),
                "restored_from_backup",
                "fake-password-value",
            ),
        ]
    )
    def test_restore_puts_full_inputs_back_and_clears_the_marker(
        self,
        _name: str,
        change_row: Callable[[Any, ExternalDataSource], Any],
        args: tuple[str, ...],
        expected_outcome: str,
        expected_password: str,
    ) -> None:
        source = self._stripped_source()
        change_row(self, source)

        dry_run = self._run("restore_warehouse_source_connection_fields", "--source-id", str(source.id), *args)
        assert f"{expected_outcome}=1" in dry_run
        assert CONNECTION_FIELDS_STRIPPED_KEY in self._stored(source)

        self._run("restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id), *args)

        expected = {**POSTGRES_INPUTS, "password": expected_password}
        assert self._stored(source) == expected
        assert self._row(source) == {**POSTGRES_CONNECTION, "password": expected_password}
        assert len(self._backups()) == 1

    def test_restore_from_backup_decrypts_a_leaf_with_an_extra_encryption_layer(self) -> None:
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
        source = self._backfilled_source()
        ExternalDataSource.objects.filter(pk=source.pk).update(
            job_inputs={**POSTGRES_INPUTS, "password": field.encrypt(POSTGRES_INPUTS["password"])}
        )
        self._run("strip_warehouse_source_connection_fields", "--execute")
        self._delete_row(source)

        output = self._run("restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id))

        assert "restored_from_backup=1" in output
        assert self._stored(source) == POSTGRES_INPUTS
        assert self._row(source) == POSTGRES_CONNECTION

    def test_restore_without_row_or_backup_changes_nothing(self) -> None:
        source = self._stripped_source()
        self._delete_row(source)
        ExternalDataSourceInputsBackup.objects.unscoped().all().delete()

        out = StringIO()
        with pytest.raises(CommandError, match="neither a readable credentials row nor a backup"):
            call_command(
                "restore_warehouse_source_connection_fields", "--execute", "--team-id", str(self.team.pk), stdout=out
            )

        assert "no_row_and_no_backup=1" in out.getvalue()
        assert CONNECTION_FIELDS_STRIPPED_KEY in self._stored(source)

    def test_restore_needs_a_source_or_team(self) -> None:
        with pytest.raises(CommandError):
            self._run("restore_warehouse_source_connection_fields", "--execute")


class TestPruneWarehouseSourceInputsBackups(_StripTestCase):
    def test_prune_deletes_only_backups_older_than_the_window(self) -> None:
        now = datetime(2026, 6, 1, tzinfo=UTC)
        for age_days in (40, 31, 10):
            with time_machine.travel(now - timedelta(days=age_days), tick=False):
                ExternalDataSourceInputsBackup.objects.for_team(self.team.pk).create(
                    team=self.team, source_id=self._source().id, source_type="Postgres", inputs=POSTGRES_INPUTS
                )

        with time_machine.travel(now, tick=False):
            dry_run = self._run("prune_warehouse_source_inputs_backups")
            assert "matched=2 deleted=0" in dry_run
            assert len(self._backups()) == 3

            output = self._run("prune_warehouse_source_inputs_backups", "--execute", "--older-than-days", "30")

        assert "matched=2 deleted=2" in output
        assert [backup.created_at for backup in self._backups()] == [now - timedelta(days=10)]

    def test_prune_rejects_a_window_below_one_day(self) -> None:
        with pytest.raises(CommandError):
            self._run("prune_warehouse_source_inputs_backups", "--older-than-days", "0")


def _with_int_pointers(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _with_int_pointers(value)
        if isinstance(value, dict)
        else (int(value) if key.endswith("_integration_id") else value)
        for key, value in inputs.items()
    }
