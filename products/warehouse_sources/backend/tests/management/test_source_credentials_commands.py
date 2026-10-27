from datetime import timedelta
from io import StringIO
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from cryptography.fernet import Fernet
from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.team import Team

from products.warehouse_sources.backend.logic import source_credentials_sync
from products.warehouse_sources.backend.logic.source_credentials import WarehouseSourceCredentialsStore
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

POSTGRES_INPUTS: dict[str, Any] = {
    "host": "db.example.com",
    "port": "5432",
    "user": "reader",
    "password": "fake-password-value",
    "database": "app",
    "schema": "public",
}
POSTGRES_CONNECTION = {key: POSTGRES_INPUTS[key] for key in ("host", "port", "user", "password", "database")}


class _CredentialsCommandTestCase(BaseTest):
    def _source(
        self,
        job_inputs: Any = None,
        *,
        team: Team | None = None,
        source_type: str = ExternalDataSourceType.POSTGRES,
        deleted: bool = False,
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team or self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status="Completed",
            source_type=source_type,
            job_inputs=POSTGRES_INPUTS if job_inputs is None else job_inputs,
            deleted=deleted,
        )

    def _rows(self) -> list[Integration]:
        return list(Integration.objects.filter(kind="warehouse-source"))

    def _run(self, command: str, *args: str) -> str:
        out = StringIO()
        call_command(command, *args, stdout=out)
        return out.getvalue()


class TestBackfillWarehouseSourceCredentials(_CredentialsCommandTestCase):
    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        self._source()

        output = self._run("backfill_warehouse_source_credentials")

        assert "Dry run" in output
        assert "created=1" in output
        assert self._rows() == []

    def test_execute_stores_only_connection_fields_and_never_prints_values(self) -> None:
        source = self._source()

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert WarehouseSourceCredentialsStore.get(source) == POSTGRES_CONNECTION
        assert "fake-password-value" not in output
        assert "db.example.com" not in output

    def test_second_run_is_unchanged_and_a_changed_source_is_updated(self) -> None:
        source = self._source()
        self._run("backfill_warehouse_source_credentials", "--execute")

        assert "unchanged=1" in self._run("backfill_warehouse_source_credentials", "--execute")

        source.job_inputs = {**POSTGRES_INPUTS, "password": "other-fake-password"}
        source.save()
        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "updated=1" in output
        assert WarehouseSourceCredentialsStore.get(source) == {**POSTGRES_CONNECTION, "password": "other-fake-password"}

    def test_source_without_connection_fields_gets_a_row_with_empty_fields(self) -> None:
        source = self._source({"schema": "public"})

        self._run("backfill_warehouse_source_credentials", "--execute")

        assert WarehouseSourceCredentialsStore.get(source) == {}

    @parameterized.expand(
        [
            ("other_team", {"team_id": 2}, 1),
            ("this_team", {"team_id": 1}, 1),
            ("both_teams", {"team_id": 1, "other": 1}, 2),
            ("no_match", {"team_id": 3}, 0),
        ]
    )
    def test_team_filter(self, _name: str, mapping: dict[str, int], expected_rows: int) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._source()
        self._source(team=other_team)
        ids = {1: self.team.id, 2: other_team.id, 3: 0}
        args: list[str] = []
        for key in mapping:
            args += ["--team-id", str(ids[mapping[key]] if key == "team_id" else other_team.id)]

        self._run("backfill_warehouse_source_credentials", "--execute", *args)

        assert len(self._rows()) == expected_rows

    def test_source_type_filter(self) -> None:
        postgres = self._source()
        self._source({"api_key": "fake-key"}, source_type=ExternalDataSourceType.STRIPE)

        self._run("backfill_warehouse_source_credentials", "--execute", "--source-type", "Postgres")

        assert [row.integration_id for row in self._rows()] == [str(postgres.id)]

    def test_unreadable_job_inputs_and_deleted_sources_are_skipped(self) -> None:
        self._source("this is not json")
        self._source(deleted=True)
        good = self._source()

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable=1" in output
        assert "created=1" in output
        assert [row.integration_id for row in self._rows()] == [str(good.id)]

    def test_a_rotation_after_the_batch_read_is_not_overwritten(self) -> None:
        source = self._source()
        rotated = {**POSTGRES_INPUTS, "password": "rotated-password"}
        original_upsert = WarehouseSourceCredentialsStore.upsert

        def rotate_then_upsert(target: ExternalDataSource, fields: Any) -> None:
            if fields.get("password") == POSTGRES_INPUTS["password"]:
                fresh = ExternalDataSource.objects.get(pk=source.pk)
                with patch.object(WarehouseSourceCredentialsStore, "upsert", original_upsert):
                    SourceInputsStore.save(fresh, rotated)
                    original_upsert(fresh, {k: rotated[k] for k in POSTGRES_CONNECTION})
            original_upsert(target, fields)

        with patch.object(WarehouseSourceCredentialsStore, "upsert", side_effect=rotate_then_upsert):
            self._run("backfill_warehouse_source_credentials", "--execute")

        assert WarehouseSourceCredentialsStore.get(source) == {k: rotated[k] for k in POSTGRES_CONNECTION}

    def test_an_undecryptable_leaf_is_skipped_and_keeps_the_existing_row(self) -> None:
        foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"fake-password-value").decode()
        source = self._source({**POSTGRES_INPUTS, "password": foreign_ciphertext})
        WarehouseSourceCredentialsStore.upsert(source, POSTGRES_CONNECTION)

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable=1" in output
        assert WarehouseSourceCredentialsStore.get(source) == POSTGRES_CONNECTION

    def test_batches_and_limit(self) -> None:
        for _ in range(5):
            self._source()

        self._run("backfill_warehouse_source_credentials", "--execute", "--batch-size", "2", "--limit", "3")
        assert len(self._rows()) == 3

        self._run("backfill_warehouse_source_credentials", "--execute", "--batch-size", "2")
        assert len(self._rows()) == 5

    def test_invalid_batch_size_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            self._run("backfill_warehouse_source_credentials", "--batch-size", "0")


class TestReconcileWarehouseSourceCredentials(_CredentialsCommandTestCase):
    def _orphan_setup(self) -> dict[str, ExternalDataSource]:
        live = self._source()
        deleted = self._source(deleted=True)
        other_team = Team.objects.create(organization=self.organization, name="other")
        wrong_team = self._source(team=other_team)
        for source in (live, deleted, wrong_team):
            WarehouseSourceCredentialsStore.upsert(source, POSTGRES_CONNECTION)
        # Same source id under a team that does not own it, and an id that is not a UUID.
        Integration.objects.create(team=self.team, kind="warehouse-source", integration_id=str(wrong_team.id))
        Integration.objects.create(team=self.team, kind="warehouse-source", integration_id="not-a-uuid")
        Integration.objects.create(team=self.team, kind="warehouse-source", integration_id=str(uuid4()))
        self._age_rows()
        return {"live": live, "deleted": deleted, "wrong_team": wrong_team}

    def _age_rows(self) -> None:
        old = timezone.now() - source_credentials_sync.ORPHAN_GRACE_PERIOD - timedelta(minutes=1)
        Integration.objects.filter(kind="warehouse-source").update(created_at=old)

    def test_dry_run_deletes_nothing(self) -> None:
        self._orphan_setup()

        output = self._run("reconcile_warehouse_source_credentials")

        assert "orphans=4" in output
        assert len(self._rows()) == 6

    def test_execute_deletes_orphans_and_keeps_live_rows(self) -> None:
        sources = self._orphan_setup()

        output = self._run("reconcile_warehouse_source_credentials", "--execute", "--batch-size", "2")

        assert "deleted=4" in output
        kept = {(row.team_id, row.integration_id) for row in self._rows()}
        assert kept == {
            (self.team.id, str(sources["live"].id)),
            (sources["wrong_team"].team_id, str(sources["wrong_team"].id)),
        }

    def test_a_young_row_without_a_source_is_kept(self) -> None:
        self._orphan_setup()
        Integration.objects.create(team=self.team, kind="warehouse-source", integration_id=str(uuid4()))

        output = self._run("reconcile_warehouse_source_credentials", "--execute")

        assert "deleted=4" in output
        assert len(self._rows()) == 3

    def test_verify_fails_on_a_source_of_unknown_type(self) -> None:
        self._source(source_type="NotARealSource")

        with self.assertRaises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_verify_reports_missing_and_mismatched_rows_and_fails(self) -> None:
        missing = self._source()
        mismatched = self._source()
        matching = self._source()
        WarehouseSourceCredentialsStore.upsert(mismatched, {**POSTGRES_CONNECTION, "password": "different"})
        WarehouseSourceCredentialsStore.upsert(matching, POSTGRES_CONNECTION)

        out = StringIO()
        with self.assertRaises(CommandError) as raised:
            call_command("reconcile_warehouse_source_credentials", "--verify", stdout=out)

        assert "2 sources" in str(raised.exception)
        assert "missing_row=1" in out.getvalue()
        assert "differs_or_unreadable_row=1" in out.getvalue()
        assert "unchanged=1" in out.getvalue()
        assert "different" not in out.getvalue()
        assert WarehouseSourceCredentialsStore.get(missing) is None

    def test_verify_passes_when_every_source_has_a_matching_row(self) -> None:
        self._source()
        self._run("backfill_warehouse_source_credentials", "--execute")

        assert "Verified" in self._run("reconcile_warehouse_source_credentials", "--verify")

    @parameterized.expand(
        [
            ("verify_with_execute", ["--verify", "--execute"]),
            ("filter_without_verify", ["--team-id", "1"]),
        ]
    )
    def test_invalid_option_combinations_are_rejected(self, _name: str, args: list[str]) -> None:
        with self.assertRaises(CommandError):
            self._run("reconcile_warehouse_source_credentials", *args)
