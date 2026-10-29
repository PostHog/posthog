from io import StringIO
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError

from cryptography.fernet import Fernet
from parameterized import parameterized

from posthog.integrations import IntegrationManager
from posthog.models.team import Team

from products.warehouse_sources.backend.facade.contracts import CREDENTIALS_REFERENCE_KEY
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
REF = CREDENTIALS_REFERENCE_KEY


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

    def _reference(self, source: ExternalDataSource) -> Any:
        return SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk)).get(REF)

    def _row_fields(self, source: ExternalDataSource) -> dict[str, Any] | None:
        return WarehouseSourceCredentialsStore.get(source, self._reference(source))

    def _rows(self, team: Team | None = None) -> list[Any]:
        return IntegrationManager.source("postgresql").credentials.list((team or self.team).pk)

    def _row_for(self, source: ExternalDataSource, fields: dict[str, Any]) -> int:
        return WarehouseSourceCredentialsStore.create(source, fields)

    def _run(self, command: str, *args: str) -> str:
        out = StringIO()
        call_command(command, *args, stdout=out)
        return out.getvalue()


class TestBackfillWarehouseSourceCredentials(_CredentialsCommandTestCase):
    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        source = self._source()

        output = self._run("backfill_warehouse_source_credentials")

        assert "Dry run" in output
        assert "created=1" in output
        assert self._rows() == []
        assert self._reference(source) is None

    def test_execute_creates_one_row_per_source_and_never_prints_values(self) -> None:
        first = self._source()
        second = self._source()

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert self._row_fields(first) == POSTGRES_CONNECTION
        assert self._row_fields(second) == POSTGRES_CONNECTION
        assert self._reference(first) != self._reference(second)
        assert SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=first.pk)) == {
            **POSTGRES_INPUTS,
            REF: self._reference(first),
        }
        assert "fake-password-value" not in output
        assert "db.example.com" not in output

    def test_second_run_is_unchanged_and_a_changed_source_updates_its_row(self) -> None:
        source = self._source()
        self._run("backfill_warehouse_source_credentials", "--execute")
        reference = self._reference(source)

        assert "unchanged=1" in self._run("backfill_warehouse_source_credentials", "--execute")

        ExternalDataSource.objects.filter(pk=source.pk).update(
            job_inputs={**POSTGRES_INPUTS, "password": "other-fake-password", REF: reference}
        )
        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "updated=1" in output
        assert self._reference(source) == reference
        assert self._row_fields(source) == {**POSTGRES_CONNECTION, "password": "other-fake-password"}
        assert len(self._rows()) == 1

    @parameterized.expand(
        [
            ("no_connection_fields", ExternalDataSourceType.POSTGRES, {"schema": "public"}),
            ("oauth_only", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": "7"}),
            (
                "oauth_option",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}},
            ),
        ]
    )
    def test_source_without_typed_in_credentials_gets_no_row(
        self, _name: str, source_type: str, job_inputs: dict[str, Any]
    ) -> None:
        source = self._source(job_inputs, source_type=source_type)

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_no_row=1" in output
        assert IntegrationManager.any.with_source_rows().list(self.team.pk) == []
        assert self._reference(source) is None

    @parameterized.expand(
        [
            ("other_team", ["other"], 0, 1),
            ("this_team", ["this"], 1, 0),
            ("both_teams", ["this", "other"], 1, 1),
            ("no_match", ["none"], 0, 0),
        ]
    )
    def test_team_filter(self, _name: str, teams: list[str], this_rows: int, other_rows: int) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        self._source()
        self._source(team=other_team)
        ids = {"this": self.team.id, "other": other_team.id, "none": 0}
        args = [arg for team in teams for arg in ("--team-id", str(ids[team]))]

        self._run("backfill_warehouse_source_credentials", "--execute", *args)

        assert len(self._rows()) == this_rows
        assert len(self._rows(other_team)) == other_rows

    def test_source_type_filter(self) -> None:
        postgres = self._source()
        stripe = self._source(
            {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake-key"}},
            source_type=ExternalDataSourceType.STRIPE,
        )

        self._run("backfill_warehouse_source_credentials", "--execute", "--source-type", "Postgres")

        assert [row.id for row in self._rows()] == [int(self._reference(postgres))]
        assert self._reference(stripe) is None

    def test_unreadable_job_inputs_and_deleted_sources_are_skipped(self) -> None:
        self._source("this is not json")
        deleted = self._source(deleted=True)
        good = self._source()

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable=1" in output
        assert "created=1" in output
        assert [row.id for row in self._rows()] == [int(self._reference(good))]
        assert self._reference(deleted) is None

    def test_a_rotation_after_the_batch_read_is_not_overwritten(self) -> None:
        source = self._source()
        rotated = {**POSTGRES_INPUTS, "password": "rotated-password"}
        original = source_credentials_sync._sync_source

        def rotate_then_sync(target: ExternalDataSource) -> str:
            ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=rotated)
            return original(target)

        with patch.object(source_credentials_sync, "_sync_source", side_effect=rotate_then_sync):
            self._run("backfill_warehouse_source_credentials", "--execute")

        assert self._row_fields(source) == {**POSTGRES_CONNECTION, "password": "rotated-password"}

    def test_a_reference_written_after_the_batch_read_gets_an_update_not_a_second_row(self) -> None:
        source = self._source()
        original = source_credentials_sync._sync_source

        def link_then_sync(target: ExternalDataSource) -> str:
            pk = self._row_for(source, {**POSTGRES_CONNECTION, "password": "old"})
            ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs={**POSTGRES_INPUTS, REF: pk})
            return original(target)

        with patch.object(source_credentials_sync, "_sync_source", side_effect=link_then_sync):
            output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "updated=1" in output
        assert len(self._rows()) == 1
        assert self._row_fields(source) == POSTGRES_CONNECTION

    def test_an_undecryptable_leaf_is_skipped_and_keeps_the_existing_row(self) -> None:
        foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"fake-password-value").decode()
        source = self._source({**POSTGRES_INPUTS, "password": foreign_ciphertext})
        pk = self._row_for(source, POSTGRES_CONNECTION)
        ExternalDataSource.objects.filter(pk=source.pk).update(
            job_inputs={**POSTGRES_INPUTS, "password": foreign_ciphertext, REF: pk}
        )

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable=1" in output
        assert self._row_fields(source) == POSTGRES_CONNECTION

    def test_a_dangling_reference_gets_a_new_row(self) -> None:
        source = self._source({**POSTGRES_INPUTS, REF: "999999999"})

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "recreated=1" in output
        assert self._reference(source) != "999999999"
        assert self._row_fields(source) == POSTGRES_CONNECTION

    def test_a_shared_row_with_other_values_is_not_written(self) -> None:
        owner = self._source()
        pk = self._row_for(owner, POSTGRES_CONNECTION)
        ExternalDataSource.objects.filter(pk=owner.pk).update(job_inputs={**POSTGRES_INPUTS, REF: pk})
        other = self._source({**POSTGRES_INPUTS, "password": "other-fake-password", REF: pk})

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_shared=1" in output
        assert self._row_fields(other) == POSTGRES_CONNECTION

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
    def test_reports_dangling_references_and_writes_nothing(self) -> None:
        linked = self._source()
        pk = self._row_for(linked, POSTGRES_CONNECTION)
        ExternalDataSource.objects.filter(pk=linked.pk).update(job_inputs={**POSTGRES_INPUTS, REF: pk})
        hubspot_row = IntegrationManager.hubspot.oauth.create(self.team.pk, external_id="hub", config={})
        self._source({"hubspot_integration_id": str(hubspot_row.id)}, source_type=ExternalDataSourceType.HUBSPOT)
        typed_in_dangling = self._source({**POSTGRES_INPUTS, REF: "999999999"})
        oauth_dangling = self._source(
            {"hubspot_integration_id": "999999998"}, source_type=ExternalDataSourceType.HUBSPOT
        )
        nested_dangling = self._source(
            {"auth_method": {"selection": "oauth", "stripe_integration_id": "999999997"}},
            source_type=ExternalDataSourceType.STRIPE,
        )
        other_team = Team.objects.create(organization=self.organization, name="other")
        other_team_row = IntegrationManager.hubspot.oauth.create(other_team.pk, external_id="hub", config={})
        cross_team = self._source(
            {"hubspot_integration_id": str(other_team_row.id)}, source_type=ExternalDataSourceType.HUBSPOT
        )
        self._source({"auth_oauth2_integration_id": "999999996"}, source_type=ExternalDataSourceType.CUSTOM)

        output = self._run("reconcile_warehouse_source_credentials")

        assert "references=6 dangling=4" in output
        for source, key in [
            (typed_in_dangling, REF),
            (oauth_dangling, "hubspot_integration_id"),
            (nested_dangling, "stripe_integration_id"),
            (cross_team, "hubspot_integration_id"),
        ]:
            assert f"source={source.id} type={source.source_type} key={key}" in output
        assert "fake-password-value" not in output
        assert self._reference(typed_in_dangling) == "999999999"
        assert len(self._rows()) == 1

    def test_verify_fails_on_a_source_of_unknown_type(self) -> None:
        self._source(source_type="NotARealSource")

        with self.assertRaises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_verify_reports_missing_and_mismatched_rows_and_fails(self) -> None:
        self._source()
        mismatched = self._source()
        matching = self._source()
        for source, fields in [
            (mismatched, {**POSTGRES_CONNECTION, "password": "different"}),
            (matching, POSTGRES_CONNECTION),
        ]:
            pk = self._row_for(source, fields)
            ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs={**POSTGRES_INPUTS, REF: pk})

        out = StringIO()
        with self.assertRaises(CommandError) as raised:
            call_command("reconcile_warehouse_source_credentials", "--verify", stdout=out)

        assert "2 sources" in str(raised.exception)
        assert "missing_reference=1" in out.getvalue()
        assert "differs_or_unreadable_row=1" in out.getvalue()
        assert "unchanged=1" in out.getvalue()
        assert "different" not in out.getvalue()

    def test_verify_fails_on_a_dangling_reference(self) -> None:
        self._source({"hubspot_integration_id": "999999998"}, source_type=ExternalDataSourceType.HUBSPOT)

        with self.assertRaises(CommandError) as raised:
            self._run("reconcile_warehouse_source_credentials", "--verify")

        assert "1 references point at no row" in str(raised.exception)

    def test_verify_passes_when_every_source_has_a_matching_row(self) -> None:
        self._source()
        self._run("backfill_warehouse_source_credentials", "--execute")

        assert "Verified" in self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_invalid_batch_size_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--batch-size", "0")
