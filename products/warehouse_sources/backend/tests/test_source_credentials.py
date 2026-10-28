import csv
from typing import Any, cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from cryptography.fernet import Fernet
from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.models.integration import ANY, WAREHOUSE_SOURCE_TYPE_CONFIG_KEY, Integration
from posthog.models.integration.auth_types import catalogued_kinds, kind_auth_types
from posthog.models.integration.model import integration_kind_choices
from posthog.models.team import Team

from products.warehouse_sources.backend.facade.contracts import CREDENTIALS_REFERENCE_KEY, SharedCredentialsError
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
from products.warehouse_sources.backend.logic.credential_auth_types import (
    INSTALLED_AUTH_TYPES,
    typed_in_auth_type,
    typed_in_auth_types,
)
from products.warehouse_sources.backend.logic.integration_references import list_sources_using_integration
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadable,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.presentation.views.external_data_source.shared_credentials import (
    shared_credentials_conflict_response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    JobInputKind,
    classify_job_input_key,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.workflows.backend.facade.contracts import WorkflowSummary

PG_FIELDS: dict[str, Any] = {
    "host": "db.example.com",
    "port": "5432",
    "user": "reader",
    "password": "fake-password",
    "ssh_tunnel": {"enabled": "True"},
}


class TestWarehouseSourceCredentialsStore(BaseTest):
    def _source(
        self, source_type: ExternalDataSourceType = ExternalDataSourceType.POSTGRES, team: Team | None = None
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=team or self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status="Completed",
            source_type=source_type,
            job_inputs={"schema": "public"},
            created_by=self.user,
        )

    def _referencing(self, ref: int, source_type: ExternalDataSourceType = ExternalDataSourceType.POSTGRES) -> None:
        source = self._source(source_type)
        source.job_inputs = {CREDENTIALS_REFERENCE_KEY: str(ref)}
        source.save()

    @parameterized.expand(
        [
            ("postgres_default_auth", ExternalDataSourceType.POSTGRES, PG_FIELDS, "postgresql", "password", False),
            (
                "stripe_api_key_on_oauth_kind",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake-key"}},
                "stripe",
                "api_key",
                True,
            ),
            (
                "github_pat_on_app_kind",
                ExternalDataSourceType.GITHUB,
                {"auth_method": {"selection": "pat", "personal_access_token": "fake-token"}},
                "github",
                "token",
                True,
            ),
            (
                "twilio_auth_token_default",
                ExternalDataSourceType.TWILIO,
                {"account_sid": "AC1", "auth_method": {"selection": "auth_token", "auth_token": "fake"}},
                "twilio",
                "auth_token",
                False,
            ),
            (
                "twilio_api_key_selection",
                ExternalDataSourceType.TWILIO,
                {"account_sid": "AC1", "auth_method": {"selection": "api_key", "api_key_secret": "fake"}},
                "twilio",
                "api_key",
                True,
            ),
            (
                "databricks_missing_selection_uses_config_default",
                ExternalDataSourceType.DATABRICKS,
                {"host": "dbc.example.com", "auth_type": {"access_token": "fake"}},
                "databricks",
                "access_token",
                True,
            ),
            ("generated_kind", ExternalDataSourceType.ABLY, {"api_key": "fake-key"}, "ably", "credentials", False),
        ]
    )
    def test_create_writes_a_marked_row_of_the_provider_kind_and_auth_type(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        fields: dict[str, Any],
        kind: str,
        auth_type: str,
        stores_auth_type: bool,
    ) -> None:
        source = self._source(source_type)

        pk = WarehouseSourceCredentialsStore.create(source, fields)

        row = Integration.objects.with_auth(auth_type).get(id=pk)
        assert (row.team_id, row.kind, row.auth_type, row.created_by_id) == (
            self.team.id,
            kind,
            auth_type,
            self.user.id,
        )
        assert row.config[WAREHOUSE_SOURCE_TYPE_CONFIG_KEY] == source_type.value
        assert ("auth_type" in row.config) == stores_auth_type
        assert "fake" not in str(row.config)
        assert row.integration_id and row.integration_id != str(source.id)
        assert WarehouseSourceCredentialsStore.get(source, pk) == fields
        assert WarehouseSourceCredentialsStore.get(source, str(pk)) == fields

    @parameterized.expand(
        [
            # A typed-in row on a kind with an OAuth or App default is invisible to code that did not ask for it.
            ("stripe_api_key", ExternalDataSourceType.STRIPE, {"auth_method": {"selection": "api_key"}}, False),
            ("github_token", ExternalDataSourceType.GITHUB, {"auth_method": {"selection": "pat"}}, False),
            # A row with the default auth type of its kind is visible. The marker tells other code its shape.
            ("postgres_password", ExternalDataSourceType.POSTGRES, PG_FIELDS, True),
        ]
    )
    def test_unqualified_queries_see_only_default_auth_rows(
        self, _name: str, source_type: ExternalDataSourceType, fields: dict[str, Any], visible_unqualified: bool
    ) -> None:
        pk = WarehouseSourceCredentialsStore.create(self._source(source_type), fields)

        assert Integration.objects.filter(id=pk).exists() == visible_unqualified
        assert Integration.objects.with_auth(ANY).filter(id=pk).exists()
        assert Integration.objects.with_auth(ANY).holding_warehouse_source_fields().filter(id=pk).exists()
        assert not Integration.objects.with_auth(ANY).without_warehouse_source_fields().filter(id=pk).exists()

    @parameterized.expand(
        [
            ("oauth_default_kind", ExternalDataSourceType.HUBSPOT),
            ("custom_has_no_kind", ExternalDataSourceType.CUSTOM),
        ]
    )
    def test_source_without_a_typed_in_auth_type_gets_no_row(self, _name: str, source_type: ExternalDataSourceType):
        with self.assertRaises(ValueError):
            WarehouseSourceCredentialsStore.create(self._source(source_type), {"token": "fake"})
        assert not Integration.objects.with_auth(ANY).exists()

    @parameterized.expand(
        [
            ("none", lambda store_pk, other: None),
            ("not_a_number", lambda store_pk, other: "abc"),
            ("missing_pk", lambda store_pk, other: store_pk + 1000),
            ("other_team", lambda store_pk, other: other["other_team"]),
            ("other_kind", lambda store_pk, other: other["stripe"]),
            ("unmarked_row_of_same_kind", lambda store_pk, other: other["native_postgres"]),
        ]
    )
    def test_get_returns_none_for_a_reference_the_source_cannot_use(self, _name: str, ref_of: Any) -> None:
        source = self._source()
        store_pk = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other = {
            "other_team": WarehouseSourceCredentialsStore.create(self._source(team=other_team), PG_FIELDS),
            "stripe": WarehouseSourceCredentialsStore.create(
                self._source(ExternalDataSourceType.STRIPE), {"auth_method": {"selection": "api_key"}}
            ),
            "native_postgres": Integration.objects.create(
                team=self.team, kind="postgresql", integration_id="native", sensitive_config={"fields": PG_FIELDS}
            ).pk,
        }

        ref = ref_of(store_pk, other)

        assert WarehouseSourceCredentialsStore.get(source, ref) is None
        assert WarehouseSourceCredentialsStore.get_many([(source, ref)]) == {}

    @parameterized.expand(
        [("empty_dict", {}), ("no_fields_key", {"other": 1}), ("fields_not_a_mapping", {"fields": 5})]
    )
    def test_unreadable_row_is_reported_distinctly(self, _name: str, stored: dict[str, Any]) -> None:
        source = self._source()
        pk = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
        row = Integration.objects.get(id=pk)
        row.sensitive_config = stored
        row.save()

        with self.assertRaises(CredentialsUnreadableError) as raised:
            WarehouseSourceCredentialsStore.get(source, pk)
        assert "fake-password" not in str(raised.exception)
        assert WarehouseSourceCredentialsStore.get_many([(source, pk)]) == {source.id: CredentialsUnreadable()}

    def test_undecryptable_leaf_is_unreadable_and_extra_layers_are_peeled(self) -> None:
        source, double_encrypted = self._source(), self._source()
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))  # type: ignore[misc]
        foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"fake-password").decode()
        bad = WarehouseSourceCredentialsStore.create(source, {"host": "db.example.com", "password": foreign_ciphertext})
        peeled = WarehouseSourceCredentialsStore.create(double_encrypted, {"password": field.encrypt("fake-password")})

        with self.assertRaises(CredentialsUnreadableError):
            WarehouseSourceCredentialsStore.get(source, bad)
        assert WarehouseSourceCredentialsStore.get(double_encrypted, peeled) == {"password": "fake-password"}
        assert WarehouseSourceCredentialsStore.get_many([(source, bad), (double_encrypted, peeled)]) == {
            source.id: CredentialsUnreadable(),
            double_encrypted.id: {"password": "fake-password"},
        }

    def test_get_many_uses_one_query_per_team_and_skips_rows_a_source_cannot_use(self) -> None:
        postgres, stripe, without_ref, wrong_kind = (
            self._source(),
            self._source(ExternalDataSourceType.STRIPE),
            self._source(),
            self._source(),
        )
        stripe_fields = {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake"}}
        postgres_pk = WarehouseSourceCredentialsStore.create(postgres, PG_FIELDS)
        stripe_pk = WarehouseSourceCredentialsStore.create(stripe, stripe_fields)

        with self.assertNumQueries(1):
            result = WarehouseSourceCredentialsStore.get_many(
                [(postgres, postgres_pk), (stripe, stripe_pk), (without_ref, None), (wrong_kind, stripe_pk)]
            )

        assert result == {postgres.id: PG_FIELDS, stripe.id: stripe_fields}

    @parameterized.expand(
        [
            # (name, other user, new fields, allow_shared, outcome)
            ("sole_user_secret_change", None, {**PG_FIELDS, "password": "new"}, False, "in_place"),
            ("sole_user_host_change", None, {**PG_FIELDS, "host": "new.example.com"}, False, "in_place"),
            ("shared_secret_change", "source", {**PG_FIELDS, "password": "new"}, False, "conflict"),
            ("shared_secret_change_confirmed", "source", {**PG_FIELDS, "password": "new"}, True, "in_place"),
            ("shared_with_a_workflow", "workflow", {**PG_FIELDS, "password": "new"}, False, "conflict"),
            ("shared_host_change", "source", {**PG_FIELDS, "host": "new.example.com"}, False, "new_row"),
            ("shared_user_change", "source", {**PG_FIELDS, "user": "writer"}, True, "new_row"),
            ("shared_tunnel_change", "source", {**PG_FIELDS, "ssh_tunnel": {"enabled": "False"}}, False, "new_row"),
            ("shared_same_fields_as_strings", "source", {**PG_FIELDS, "port": 5432}, False, "conflict"),
        ]
    )
    def test_update_of_a_shared_row_needs_confirmation_or_makes_a_new_row(
        self, _name: str, other_user: str | None, new_fields: dict[str, Any], allow_shared: bool, outcome: str
    ) -> None:
        source = self._source()
        pk = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
        if other_user == "source":
            self._referencing(pk)
        workflows = (
            [WorkflowSummary(id="wf1", name="Nightly sync", status="active")] if other_user == "workflow" else []
        )

        with patch("posthog.models.integration.usages.get_active_workflows_using_integration", return_value=workflows):
            if outcome == "conflict":
                with self.assertRaises(SharedCredentialsError) as raised:
                    WarehouseSourceCredentialsStore.update(source, pk, new_fields, allow_shared=allow_shared)
                assert raised.exception.integration_id == pk
                assert [usage.type for usage in raised.exception.usages] == [
                    "workflow" if other_user == "workflow" else "warehouse_source"
                ]
                assert WarehouseSourceCredentialsStore.get(source, pk) == PG_FIELDS
                return
            new_pk = WarehouseSourceCredentialsStore.update(source, str(pk), new_fields, allow_shared=allow_shared)

        if outcome == "in_place":
            assert new_pk == pk
        else:
            assert new_pk != pk
            assert WarehouseSourceCredentialsStore.get(source, pk) == PG_FIELDS
        assert WarehouseSourceCredentialsStore.get(source, new_pk) == {
            key: str(value) if key == "port" else value for key, value in new_fields.items()
        }

    @parameterized.expand(
        [
            ("sole_user_changes_auth_type_in_place", False, "api_key", True),
            ("sole_user_back_to_default", False, "auth_token", True),
            ("shared_row_auth_type_change_makes_a_new_row", True, "api_key", False),
        ]
    )
    def test_update_follows_the_auth_type_of_the_fields(
        self, _name: str, shared: bool, new_selection: str, same_row: bool
    ) -> None:
        source = self._source(ExternalDataSourceType.TWILIO)
        start = "api_key" if new_selection == "auth_token" else "auth_token"
        pk = WarehouseSourceCredentialsStore.create(
            source, {"account_sid": "AC1", "auth_method": {"selection": start, "auth_token": "fake"}}
        )
        if shared:
            self._referencing(pk, ExternalDataSourceType.TWILIO)

        new_pk = WarehouseSourceCredentialsStore.update(
            source, pk, {"account_sid": "AC1", "auth_method": {"selection": new_selection, "auth_token": "fake"}}
        )

        assert (new_pk == pk) == same_row
        assert Integration.objects.with_auth(ANY).get(id=new_pk).auth_type == new_selection
        assert Integration.objects.with_auth(ANY).get(id=pk).auth_type == (new_selection if same_row else start)

    def test_update_of_a_missing_row_raises(self) -> None:
        with self.assertRaises(CredentialsNotFoundError):
            WarehouseSourceCredentialsStore.update(self._source(), 12345, PG_FIELDS)

    @parameterized.expand(
        [
            ("orphan", False, True),
            ("still_used_by_another_source", True, False),
        ]
    )
    def test_release_never_deletes_the_row(self, _name: str, shared: bool, orphaned: bool) -> None:
        source = self._source()
        pk = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
        if shared:
            self._referencing(pk)

        assert WarehouseSourceCredentialsStore.release(source, pk) is orphaned
        assert Integration.objects.with_auth(ANY).filter(id=pk).exists()

    def test_release_of_a_reference_the_source_cannot_use_is_a_no_op(self) -> None:
        source = self._source()
        oauth_row = Integration.objects.create(team=self.team, kind="hubspot", integration_id="H1")

        assert WarehouseSourceCredentialsStore.release(source, oauth_row.pk) is False
        assert WarehouseSourceCredentialsStore.release(source, None) is False

    @patch("products.warehouse_sources.backend.models.external_data_source.capture_exception")
    def test_soft_delete_keeps_the_row_and_survives_store_failure(self, capture: Any) -> None:
        deleted, failing = self._source(), self._source()
        for source in (deleted, failing):
            source.job_inputs = {CREDENTIALS_REFERENCE_KEY: WarehouseSourceCredentialsStore.create(source, PG_FIELDS)}
            source.save()

        with patch.object(
            WarehouseSourceCredentialsStore, "release", wraps=WarehouseSourceCredentialsStore.release
        ) as release:
            deleted.soft_delete()
        release.assert_called_once()
        assert Integration.objects.with_auth(ANY).holding_warehouse_source_fields().count() == 2

        with patch.object(WarehouseSourceCredentialsStore, "release", side_effect=RuntimeError("boom")):
            failing.soft_delete()
        failing.refresh_from_db()
        assert failing.deleted is True
        capture.assert_called_once()

    @parameterized.expand(
        [
            ("top_level_int", {"linear_integration_id": 7}, True),
            ("top_level_string", {"linear_integration_id": "7"}, True),
            ("credentials_reference", {CREDENTIALS_REFERENCE_KEY: "7"}, True),
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

    def test_conflict_response_names_the_other_users(self) -> None:
        source = self._source()
        pk = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
        self._referencing(pk)
        with self.assertRaises(SharedCredentialsError) as raised:
            WarehouseSourceCredentialsStore.update(source, pk, {**PG_FIELDS, "password": "new"})

        response = shared_credentials_conflict_response(raised.exception)

        assert response.status_code == 409
        assert response.data["code"] == "shared_credentials"
        assert response.data["integration_id"] == pk
        assert [usage["type"] for usage in response.data["usages"]] == ["warehouse_source"]
        assert "update_shared_credentials=true" in response.data["detail"]


def _typed_in_source_types() -> list[str]:
    """Source types that can have a typed-in row: connection fields, and no top-level OAuth reference."""
    with open(CLASSIFICATION_AUDIT_PATH) as audit:
        rows = list(csv.DictReader(audit))
    return [
        row["source_type"]
        for row in rows
        if row["credential_kind"]
        and row["connection_fields"]
        and not any("=" not in name for name in row["reference_fields"].split())
    ]


class TestCredentialAuthTypes(SimpleTestCase):
    def test_every_typed_in_source_type_has_auth_types_its_kind_supports(self) -> None:
        source_types = _typed_in_source_types()
        assert len(source_types) > 800

        for source_type in source_types:
            kind = CREDENTIAL_KINDS[source_type]
            auth_types = typed_in_auth_types(source_type)
            assert auth_types, source_type
            assert not auth_types & INSTALLED_AUTH_TYPES, source_type
            assert auth_types <= kind_auth_types(kind).supported, source_type

    def test_every_credential_kind_is_a_valid_stored_kind(self) -> None:
        stored_kinds = {value for value, _ in integration_kind_choices()}
        known = catalogued_kinds()

        for kind in set(CREDENTIAL_KINDS.values()):
            assert kind in stored_kinds, kind
            assert kind in known, kind

    @parameterized.expand(
        [
            ("unknown_option", ExternalDataSourceType.TWILIO, {"auth_method": {"selection": "magic"}}),
            ("oauth_only_source", ExternalDataSourceType.LINEAR, {}),
        ]
    )
    def test_typed_in_auth_type_rejects_what_a_typed_in_row_cannot_be(
        self, _name: str, source_type: ExternalDataSourceType, fields: dict[str, Any]
    ) -> None:
        with self.assertRaises(ValueError):
            typed_in_auth_type(source_type.value, fields)

    @parameterized.expand(
        [
            ("postgres", ExternalDataSourceType.POSTGRES),
            ("stripe_select_reference_source", ExternalDataSourceType.STRIPE),
            ("generated_kind", ExternalDataSourceType.ABLY),
        ]
    )
    def test_credentials_reference_key_is_a_reference(self, _name: str, source_type: ExternalDataSourceType) -> None:
        assert classify_job_input_key(source_type, CREDENTIALS_REFERENCE_KEY, "12") == JobInputKind.REFERENCE
