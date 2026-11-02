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
COLUMN = "credentials_integration_id"


class _CredentialsCommandTestCase(BaseTest):
    def _source(
        self,
        job_inputs: Any = None,
        *,
        team: Team | None = None,
        source_type: str = ExternalDataSourceType.POSTGRES,
        deleted: bool = False,
        column: str | None = None,
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team or self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status="Completed",
            source_type=source_type,
            job_inputs=POSTGRES_INPUTS if job_inputs is None else job_inputs,
            deleted=deleted,
            credentials_integration_id=column,
        )

    def _reference(self, source: ExternalDataSource) -> str | None:
        return ExternalDataSource.objects.get(pk=source.pk).credentials_integration_id

    def _row_fields(self, source: ExternalDataSource) -> dict[str, Any] | None:
        return WarehouseSourceCredentialsStore.get(ExternalDataSource.objects.get(pk=source.pk))

    def _rows(self, team: Team | None = None) -> list[Any]:
        return IntegrationManager.source("postgresql").credentials.list((team or self.team).pk)

    def _row_for(self, source: ExternalDataSource, fields: dict[str, Any]) -> str:
        return str(WarehouseSourceCredentialsStore.create(ExternalDataSource.objects.get(pk=source.pk), fields))

    def _link(self, source: ExternalDataSource, reference: str) -> None:
        ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id=reference)

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
        assert SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=first.pk)) == POSTGRES_INPUTS
        assert "fake-password-value" not in output
        assert "db.example.com" not in output

    def test_second_run_is_unchanged_and_a_changed_source_updates_its_row(self) -> None:
        source = self._source()
        self._run("backfill_warehouse_source_credentials", "--execute")
        reference = self._reference(source)

        assert "unchanged=1" in self._run("backfill_warehouse_source_credentials", "--execute")

        ExternalDataSource.objects.filter(pk=source.pk).update(
            job_inputs={**POSTGRES_INPUTS, "password": "other-fake-password"}
        )
        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "updated=1" in output
        assert self._reference(source) == reference
        assert self._row_fields(source) == {**POSTGRES_CONNECTION, "password": "other-fake-password"}
        assert len(self._rows()) == 1

    @parameterized.expand(
        [
            (
                "no_connection_fields",
                ExternalDataSourceType.POSTGRES,
                {"schema": "public"},
                None,
                "skipped_no_row",
                None,
            ),
            ("oauth_only", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": "7"}, None, "oauth_linked", "7"),
            (
                "oauth_short_key",
                ExternalDataSourceType.SNAPCHATADS,
                {"snapchat_integration_id": "7"},
                None,
                "oauth_linked",
                "7",
            ),
            (
                "oauth_option",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}},
                None,
                "oauth_linked",
                "7",
            ),
            (
                "bigquery_service_account",
                ExternalDataSourceType.BIGQUERY,
                {"auth_type": {"selection": "service_account", "google_cloud_service_account_integration_id": "7"}},
                None,
                "oauth_linked",
                "7",
            ),
            (
                "slack_hidden_key",
                ExternalDataSourceType.SLACK,
                {"slack_integration_id": "7"},
                None,
                "oauth_linked",
                "7",
            ),
            (
                "oauth_column_already_set",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                "7",
                "unchanged",
                "7",
            ),
            (
                "oauth_column_differs",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                "8",
                "oauth_linked",
                "7",
            ),
            # The inputs hold no pointer, so they cannot tell the row. The column stays as it is.
            ("oauth_without_pointer", ExternalDataSourceType.HUBSPOT, {}, "7", "skipped_no_row", "7"),
        ]
    )
    def test_source_without_typed_in_credentials_gets_no_row(
        self,
        _name: str,
        source_type: str,
        job_inputs: dict[str, Any],
        column: str | None,
        outcome: str,
        expected_column: str | None,
    ) -> None:
        source = self._source(job_inputs, source_type=source_type, column=column)

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert f"{outcome}=1" in output
        assert IntegrationManager.any.with_source_rows().list(self.team.pk) == []
        assert self._reference(source) == expected_column
        assert SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk)) == job_inputs

    @parameterized.expand(
        [
            ("select_as_bare_string", {"auth_method": "oauth", "stripe_integration_id": "7"}),
            ("flat_legacy_pointer", {"stripe_integration_id": "7"}),
            ("unknown_selection", {"auth_method": {"selection": "legacy", "stripe_integration_id": "7"}}),
        ]
    )
    def test_a_shape_the_walk_cannot_read_is_logged_and_skipped(self, _name: str, job_inputs: dict[str, Any]) -> None:
        source = self._source(job_inputs, source_type=ExternalDataSourceType.STRIPE)

        with patch.object(source_credentials_sync.logger, "warning") as warning:
            output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable_shape=1" in output
        assert self._reference(source) is None
        assert IntegrationManager.any.with_source_rows().list(self.team.pk) == []
        warning.assert_called_once()

    def test_a_stale_pointer_under_the_other_option_does_not_hide_typed_in_credentials(self) -> None:
        source = self._source(
            {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake-key", "stripe_integration_id": "7"}},
            source_type=ExternalDataSourceType.STRIPE,
        )

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "created=1" in output
        [row] = IntegrationManager.source("stripe").token.list(self.team.pk)
        assert self._reference(source) == str(row.id)

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

        assert [row.id for row in self._rows()] == [int(self._reference(postgres) or 0)]
        assert self._reference(stripe) is None

    def test_unreadable_job_inputs_and_deleted_sources_are_skipped(self) -> None:
        self._source("this is not json")
        deleted = self._source(deleted=True)
        good = self._source()

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable=1" in output
        assert "created=1" in output
        assert [row.id for row in self._rows()] == [int(self._reference(good) or 0)]
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
            self._link(source, self._row_for(source, {**POSTGRES_CONNECTION, "password": "old"}))
            return original(target)

        with patch.object(source_credentials_sync, "_sync_source", side_effect=link_then_sync):
            output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "updated=1" in output
        assert len(self._rows()) == 1
        assert self._row_fields(source) == POSTGRES_CONNECTION

    def test_an_undecryptable_leaf_is_skipped_and_keeps_the_existing_row(self) -> None:
        foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"fake-password-value").decode()
        source = self._source({**POSTGRES_INPUTS, "password": foreign_ciphertext})
        self._link(source, self._row_for(source, POSTGRES_CONNECTION))

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "skipped_unreadable=1" in output
        assert self._row_fields(source) == POSTGRES_CONNECTION

    def test_a_dangling_reference_gets_a_new_row(self) -> None:
        source = self._source(column="999999999")

        output = self._run("backfill_warehouse_source_credentials", "--execute")

        assert "recreated=1" in output
        assert self._reference(source) != "999999999"
        assert self._row_fields(source) == POSTGRES_CONNECTION

    def test_a_shared_row_with_other_values_is_not_written(self) -> None:
        owner = self._source()
        pk = self._row_for(owner, POSTGRES_CONNECTION)
        self._link(owner, pk)
        other = self._source({**POSTGRES_INPUTS, "password": "other-fake-password"}, column=pk)

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
        self._link(linked, self._row_for(linked, POSTGRES_CONNECTION))
        hubspot_row = IntegrationManager.hubspot.oauth.create(self.team.pk, external_id="hub", config={})
        self._source({"hubspot_integration_id": str(hubspot_row.id)}, source_type=ExternalDataSourceType.HUBSPOT)
        typed_in_dangling = self._source(column="999999999")
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
            (typed_in_dangling, COLUMN),
            (oauth_dangling, "hubspot_integration_id"),
            (nested_dangling, "stripe_integration_id"),
            (cross_team, "hubspot_integration_id"),
        ]:
            assert f"source={source.id} type={source.source_type} key={key}" in output
        assert "fake-password-value" not in output
        assert self._reference(typed_in_dangling) == "999999999"
        assert len(self._rows()) == 1

    @parameterized.expand(
        [
            # (name, inputs pointer, column, mismatched, dangling)
            ("column_differs_from_the_in_use_pointer", "first", "second", True, False),
            ("column_matches", "first", "first", False, False),
            ("column_names_no_row", "first", "999999999", True, True),
            ("column_is_a_uuid", "first", "0b7e8c3a-5f4d-4e2a-9c1b-2d3e4f5a6b7c", True, True),
            ("column_without_pointer_in_inputs", None, "999999999", False, True),
        ]
    )
    def test_reports_an_oauth_column_that_differs_or_dangles(
        self, _name: str, pointer: str | None, column: str, mismatched: bool, dangling: bool
    ) -> None:
        rows = {
            name: str(IntegrationManager.hubspot.oauth.create(self.team.pk, external_id=name, config={}).id)
            for name in ("first", "second")
        }
        source = self._source(
            {} if pointer is None else {"hubspot_integration_id": rows[pointer]},
            source_type=ExternalDataSourceType.HUBSPOT,
            column=rows.get(column, column),
        )

        output = self._run("reconcile_warehouse_source_credentials")

        assert (f"mismatched: team={self.team.pk} source={source.id}" in output) == mismatched
        assert (f"dangling: team={self.team.pk} source={source.id} type=Hubspot key={COLUMN}" in output) == dangling
        assert f"mismatched={int(mismatched)}" in output

    def test_verify_fails_on_a_column_that_differs_from_the_in_use_pointer(self) -> None:
        first, second = (
            str(IntegrationManager.hubspot.oauth.create(self.team.pk, external_id=name, config={}).id)
            for name in ("first", "second")
        )
        self._source({"hubspot_integration_id": first}, source_type=ExternalDataSourceType.HUBSPOT, column=second)

        with self.assertRaises(CommandError) as raised:
            self._run("reconcile_warehouse_source_credentials", "--verify")

        assert "1 columns differ from the inputs" in str(raised.exception)

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
            self._link(source, self._row_for(source, fields))

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
        hubspot_row = IntegrationManager.hubspot.oauth.create(self.team.pk, external_id="hub", config={})
        self._source({"hubspot_integration_id": str(hubspot_row.id)}, source_type=ExternalDataSourceType.HUBSPOT)
        self._run("backfill_warehouse_source_credentials", "--execute")

        assert "Verified" in self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_a_row_without_an_optional_key_matches_job_inputs_that_hold_it_as_none(self) -> None:
        # A parsed config writes its unset optional fields as None, and the store does not rewrite the row for that.
        source = self._source({**POSTGRES_INPUTS, "connection_string": None})
        self._link(source, self._row_for(source, POSTGRES_CONNECTION))

        assert "unchanged=1" in self._run("backfill_warehouse_source_credentials")
        assert "Verified" in self._run("reconcile_warehouse_source_credentials", "--verify")

    def test_invalid_batch_size_is_rejected(self) -> None:
        with self.assertRaises(CommandError):
            self._run("reconcile_warehouse_source_credentials", "--batch-size", "0")
