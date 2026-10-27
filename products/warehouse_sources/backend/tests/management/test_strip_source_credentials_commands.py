from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import StringIO
from typing import Any

import pytest
import time_machine
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models.integration import Integration

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
        WarehouseSourceCredentialsStore.upsert(source, POSTGRES_CONNECTION)
        return source

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk))

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
            ("missing_row", lambda case, source: WarehouseSourceCredentialsStore.delete(source), "skipped_missing_row"),
            (
                "unreadable_row",
                lambda case, source: Integration.objects.filter(kind="warehouse-source").update(sensitive_config={}),
                "skipped_unreadable_row",
            ),
            (
                "row_differs",
                lambda case, source: WarehouseSourceCredentialsStore.upsert(
                    source, {**POSTGRES_CONNECTION, "password": "fake-other"}
                ),
                "skipped_row_differs",
            ),
        ]
    )
    def test_a_source_that_fails_a_check_is_not_stripped(
        self, _name: str, break_check: Callable[[Any, ExternalDataSource], Any], expected_outcome: str
    ) -> None:
        source = self._backfilled_source()
        break_check(self, source)

        output = self._run("strip_warehouse_source_connection_fields", "--execute")

        assert f"{expected_outcome}=1" in output
        assert self._stored(source) == POSTGRES_INPUTS
        assert self._backups() == []

    def test_rerun_keeps_the_first_backup(self) -> None:
        source = self._backfilled_source()
        self._run("strip_warehouse_source_connection_fields", "--execute")
        assert "already_stripped=1" in self._run("strip_warehouse_source_connection_fields", "--execute")

        self._run("restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id))
        reloaded = ExternalDataSource.objects.get(pk=source.pk)
        SourceInputsStore.save(reloaded, {**SourceInputsStore.load(reloaded), "schema": "analytics"})
        assert "stripped=1" in self._run("strip_warehouse_source_connection_fields", "--execute")

        assert [backup.inputs for backup in self._backups()] == [POSTGRES_INPUTS]
        assert self._stored(source)["schema"] == "analytics"

    def test_backfill_never_overwrites_the_row_of_a_stripped_source(self) -> None:
        source = self._backfilled_source()
        self._run("strip_warehouse_source_connection_fields", "--execute")

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_stripped=1" in output
        assert WarehouseSourceCredentialsStore.get(source) == POSTGRES_CONNECTION

        WarehouseSourceCredentialsStore.delete(source)
        with pytest.raises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_backfill_rechecks_a_source_stripped_after_its_batch_was_read(self) -> None:
        source = self._backfilled_source()
        stale = ExternalDataSource.objects.get(pk=source.pk)
        self._run("strip_warehouse_source_connection_fields", "--execute")
        rotated = {**POSTGRES_CONNECTION, "password": "fake-rotated"}
        WarehouseSourceCredentialsStore.upsert(source, rotated)

        counts: Counter[tuple[str, str]] = Counter()
        _process_batch([stale], True, counts)

        assert counts == Counter({("Postgres", SKIPPED_STRIPPED): 1})
        assert WarehouseSourceCredentialsStore.get(source) == rotated


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
                lambda source: WarehouseSourceCredentialsStore.upsert(
                    source, {**POSTGRES_CONNECTION, "password": "fake-rotated"}
                ),
                (),
                "restored_from_row",
                "fake-rotated",
            ),
            (
                "missing_row",
                lambda source: WarehouseSourceCredentialsStore.delete(source),
                (),
                "restored_from_backup",
                "fake-password-value",
            ),
            (
                "prefer_backup",
                lambda source: WarehouseSourceCredentialsStore.upsert(source, {}),
                ("--prefer-backup",),
                "restored_from_backup",
                "fake-password-value",
            ),
        ]
    )
    def test_restore_puts_full_inputs_back_and_clears_the_marker(
        self,
        _name: str,
        change_row: Callable[[ExternalDataSource], Any],
        args: tuple[str, ...],
        expected_outcome: str,
        expected_password: str,
    ) -> None:
        source = self._stripped_source()
        change_row(source)

        dry_run = self._run("restore_warehouse_source_connection_fields", "--source-id", str(source.id), *args)
        assert f"{expected_outcome}=1" in dry_run
        assert CONNECTION_FIELDS_STRIPPED_KEY in self._stored(source)

        self._run("restore_warehouse_source_connection_fields", "--execute", "--source-id", str(source.id), *args)

        expected = {**POSTGRES_INPUTS, "password": expected_password}
        assert self._stored(source) == expected
        assert WarehouseSourceCredentialsStore.get(source) == {**POSTGRES_CONNECTION, "password": expected_password}
        assert len(self._backups()) == 1

    def test_restore_without_row_or_backup_changes_nothing(self) -> None:
        source = self._stripped_source()
        WarehouseSourceCredentialsStore.delete(source)
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
