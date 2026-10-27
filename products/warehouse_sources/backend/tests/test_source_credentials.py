from typing import Any, cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from cryptography.fernet import Fernet
from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.integration import Integration
from posthog.models.team import Team

from products.warehouse_sources.backend.logic.integration_references import list_sources_using_integration
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsUnreadable,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

FIELDS: dict[str, Any] = {"host": "db.example.com", "password": "fake-password", "ssh_tunnel": {"enabled": "True"}}


class TestWarehouseSourceCredentialsStore(BaseTest):
    def _source(self, team: Team | None = None) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team or self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status="Completed",
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs={"host": "legacy"},
        )

    def _row(self, source: ExternalDataSource) -> Integration:
        return Integration.objects.get(kind="warehouse-source", integration_id=str(source.id))

    def test_round_trip_keeps_secrets_out_of_config(self) -> None:
        source = self._source()
        assert WarehouseSourceCredentialsStore.get(source) is None

        WarehouseSourceCredentialsStore.upsert(source, FIELDS)

        assert WarehouseSourceCredentialsStore.get(source) == FIELDS
        row = self._row(source)
        assert row.team_id == self.team.id
        assert row.config == {"source_type": "Postgres", "source_id": str(source.id)}
        assert "fake-password" not in str(row.config)

    def test_upsert_is_idempotent_and_replaces_fields(self) -> None:
        source = self._source()
        WarehouseSourceCredentialsStore.upsert(source, FIELDS)
        WarehouseSourceCredentialsStore.upsert(source, {"host": "new.example.com"})

        assert Integration.objects.filter(kind="warehouse-source").count() == 1
        assert WarehouseSourceCredentialsStore.get(source) == {"host": "new.example.com"}

    def test_empty_fields_are_readable_not_unreadable(self) -> None:
        source = self._source()
        WarehouseSourceCredentialsStore.upsert(source, {})
        assert WarehouseSourceCredentialsStore.get(source) == {}

    @parameterized.expand(
        [("empty_dict", {}), ("no_fields_key", {"other": 1}), ("fields_not_a_mapping", {"fields": 5})]
    )
    def test_unreadable_row_is_reported_distinctly(self, _name: str, stored: dict[str, Any]) -> None:
        source = self._source()
        Integration.objects.create(
            team=self.team, kind="warehouse-source", integration_id=str(source.id), sensitive_config=stored
        )

        with self.assertRaises(CredentialsUnreadableError) as raised:
            WarehouseSourceCredentialsStore.get(source)
        assert "fake-password" not in str(raised.exception)
        assert WarehouseSourceCredentialsStore.get_many([source]) == {source.id: CredentialsUnreadable()}

    def test_undecryptable_leaf_is_unreadable_and_extra_layers_are_peeled(self) -> None:
        source, double_encrypted = self._source(), self._source()
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))  # type: ignore[misc]
        foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"fake-password").decode()
        Integration.objects.create(
            team=self.team,
            kind="warehouse-source",
            integration_id=str(source.id),
            sensitive_config={"fields": {"host": "db.example.com", "password": foreign_ciphertext}},
        )
        Integration.objects.create(
            team=self.team,
            kind="warehouse-source",
            integration_id=str(double_encrypted.id),
            sensitive_config={"fields": {"password": field.encrypt("fake-password")}},
        )

        with self.assertRaises(CredentialsUnreadableError):
            WarehouseSourceCredentialsStore.get(source)
        assert WarehouseSourceCredentialsStore.get(double_encrypted) == {"password": "fake-password"}
        assert WarehouseSourceCredentialsStore.get_many([source, double_encrypted]) == {
            source.id: CredentialsUnreadable(),
            double_encrypted.id: {"password": "fake-password"},
        }

    def test_get_many_uses_one_query_and_skips_missing_and_other_teams(self) -> None:
        with_row, without_row, other_team_source = self._source(), self._source(), self._source()
        WarehouseSourceCredentialsStore.upsert(with_row, FIELDS)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team_source.team = other_team
        WarehouseSourceCredentialsStore.upsert(other_team_source, {"host": "other"})
        other_team_source.team = self.team

        with self.assertNumQueries(1):
            result = WarehouseSourceCredentialsStore.get_many([with_row, without_row, other_team_source])

        assert result == {with_row.id: FIELDS}

    def test_delete_removes_only_the_row_of_that_source(self) -> None:
        first, second = self._source(), self._source()
        WarehouseSourceCredentialsStore.upsert(first, FIELDS)
        WarehouseSourceCredentialsStore.upsert(second, FIELDS)

        assert WarehouseSourceCredentialsStore.delete(first) == 1
        assert WarehouseSourceCredentialsStore.delete(first) == 0
        assert WarehouseSourceCredentialsStore.get(first) is None
        assert WarehouseSourceCredentialsStore.get(second) == FIELDS

        assert WarehouseSourceCredentialsStore.delete_for_source_ids(self.team.id, [second.id]) == 1

    @patch("products.warehouse_sources.backend.models.external_data_source.capture_exception")
    def test_soft_delete_removes_the_row_and_survives_store_failure(self, capture: Any) -> None:
        deleted, failing = self._source(), self._source()
        WarehouseSourceCredentialsStore.upsert(deleted, FIELDS)
        WarehouseSourceCredentialsStore.upsert(failing, FIELDS)

        deleted.soft_delete()
        assert WarehouseSourceCredentialsStore.get(deleted) is None

        with patch.object(WarehouseSourceCredentialsStore, "delete", side_effect=RuntimeError("boom")):
            failing.soft_delete()
        failing.refresh_from_db()
        assert failing.deleted is True
        capture.assert_called_once()

    @parameterized.expand(
        [
            ("top_level_int", {"linear_integration_id": 7}, True),
            ("top_level_string", {"linear_integration_id": "7"}, True),
            ("nested", {"auth": {"hubspot_integration_id": 7}}, True),
            ("other_integration", {"linear_integration_id": 8}, False),
            ("not_a_pointer_key", {"workspace_id": 7}, False),
            ("no_inputs", None, False),
        ]
    )
    def test_reference_detection(self, _name: str, inputs: dict[str, Any] | None, expected: bool) -> None:
        source = self._source()
        source.job_inputs = inputs
        source.save()

        found = list_sources_using_integration(self.team.id, 7)

        assert [ref.id for ref in found] == ([source.id] if expected else [])
