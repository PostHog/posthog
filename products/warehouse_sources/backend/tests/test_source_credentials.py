import csv
from typing import Any, cast
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from cryptography.fernet import Fernet
from parameterized import parameterized

from posthog.helpers.encrypted_fields import EncryptedJSONField
from posthog.integrations import AuthType, IntegrationInUse, IntegrationManager, IntegrationRecord, IntegrationUsage
from posthog.models.integration import WAREHOUSE_SOURCE_TYPE_CONFIG_KEY, AuthTypeSelector, Integration
from posthog.models.integration.auth_types import catalogued_kinds, kind_auth_types
from posthog.models.integration.model import integration_kind_choices
from posthog.models.team import Team

from products.warehouse_sources.backend.facade.contracts import SharedCredentialsError
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
from products.warehouse_sources.backend.integration_usages import integration_usages
from products.warehouse_sources.backend.logic.credential_auth_types import (
    UnknownCredentialKindError,
    typed_in_auth_type,
)
from products.warehouse_sources.backend.logic.integration_references import list_sources_using_integration
from products.warehouse_sources.backend.logic.source_credentials import (
    CredentialsNotFoundError,
    CredentialsUnreadable,
    CredentialsUnreadableError,
    WarehouseSourceCredentialsStore,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.presentation.views.external_data_source.shared_credentials import (
    shared_credentials_conflict_response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.workflows.backend.facade.contracts import WorkflowSummary

PG_FIELDS: dict[str, Any] = {
    "host": "db.example.com",
    "port": "5432",
    "user": "reader",
    "password": "fake-password",
    "ssh_tunnel": {"enabled": "True"},
}

STRIPE_FIELDS: dict[str, Any] = {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake-key"}}

SNOWFLAKE_FIELDS: dict[str, Any] = {
    "account_id": "acct-1",
    "database": "analytics",
    "auth_type": {"selection": "password", "user": "reader", "password": "fake-password"},
}
PG_URL_FIELDS: dict[str, Any] = {
    "connection_string": "postgresql://reader:fake-password@db.example.com:5432/app?sslmode=require"
}
MSSQL_ADO_FIELDS: dict[str, Any] = {
    "connection_string": "Server=db.example.com,1433;User Id=reader;Password=fake-password;Database=app"
}
PG_TUNNEL_FIELDS: dict[str, Any] = {
    **PG_FIELDS,
    "ssh_tunnel": {
        "enabled": "True",
        "host": "bastion.example.com",
        "port": "22",
        "auth_type": {"selection": "keypair", "username": "tunnel", "private_key": "fake-key", "passphrase": "fake"},
    },
}


def _with(fields: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    head, _, rest = path.partition(".")
    return {**fields, head: _with(fields[head], rest, value) if rest else value}


def _row(pk: int) -> Integration:
    return Integration.objects._with_auth(AuthTypeSelector.ANY).get(id=pk)


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

    def _create(self, source: ExternalDataSource, fields: dict[str, Any]) -> int:
        reference = WarehouseSourceCredentialsStore.create(source, fields)
        SourceInputsStore.save(source, SourceInputsStore.load(source))
        assert reference.legacy_id is not None
        return reference.legacy_id

    def _referencing(self, pk: int, source_type: ExternalDataSourceType = ExternalDataSourceType.POSTGRES) -> None:
        source = self._source(source_type)
        source.credentials_integration_id = str(pk)
        source.save()

    def _fields_of_row(
        self, pk: int, source_type: ExternalDataSourceType = ExternalDataSourceType.POSTGRES
    ) -> dict[str, Any] | None:
        reader = ExternalDataSource(team=self.team, source_type=source_type, credentials_integration_id=str(pk))
        return WarehouseSourceCredentialsStore.get(reader)

    @parameterized.expand(
        [
            ("postgres_default_auth", ExternalDataSourceType.POSTGRES, PG_FIELDS, "postgresql", "credentials", False),
            ("stripe_token_on_oauth_kind", ExternalDataSourceType.STRIPE, STRIPE_FIELDS, "stripe", "token", True),
            (
                "github_token_on_oauth_kind",
                ExternalDataSourceType.GITHUB,
                {"auth_method": {"selection": "pat", "personal_access_token": "fake-token"}},
                "github",
                "token",
                True,
            ),
            (
                "twilio_credentials_on_token_kind",
                ExternalDataSourceType.TWILIO,
                {"account_sid": "AC1", "auth_method": {"selection": "api_key", "api_key_secret": "fake"}},
                "twilio",
                "credentials",
                True,
            ),
            (
                "databricks_default_auth",
                ExternalDataSourceType.DATABRICKS,
                {"host": "dbc.example.com", "auth_type": {"access_token": "fake"}},
                "databricks",
                "credentials",
                False,
            ),
            ("generated_token_kind", ExternalDataSourceType.ABLY, {"api_key": "fake-key"}, "ably", "token", False),
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

        reference = WarehouseSourceCredentialsStore.create(source, fields)

        assert reference.legacy_id is not None and reference.uuid is None
        assert source.credentials_integration_id == str(reference.legacy_id)
        row = IntegrationManager.source(kind).any.get(self.team.id, reference.legacy_id)
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
        assert WarehouseSourceCredentialsStore.get(source) == fields
        assert "credentials_integration_id" not in SourceInputsStore.load(source)

    @parameterized.expand(
        [
            ("inputs_save", lambda source: SourceInputsStore.save(source, {"schema": "other"}), True),
            ("model_save", lambda source: source.save(), True),
            # A sync holds an old copy of its source, so a runtime write must not move the pointer.
            ("runtime_write", lambda source: SourceInputsStore.update_runtime(source, {"cdc_slot_name": "s"}), False),
            ("no_save", lambda source: None, False),
        ]
    )
    def test_the_pointer_reaches_the_database_only_with_a_save_of_the_inputs(
        self, _name: str, write: Any, saved: bool
    ) -> None:
        source = self._source()

        reference = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
        write(source)

        stored = ExternalDataSource.objects.get(id=source.id).credentials_integration_id
        assert stored == (str(reference) if saved else None)

    @parameterized.expand(
        [
            ("clickup", ExternalDataSourceType.CLICKUP, "clickup"),
            ("gitlab", ExternalDataSourceType.GITLAB, "gitlab"),
            ("google_calendar", ExternalDataSourceType.GOOGLECALENDAR, "google-calendar"),
            ("jira", ExternalDataSourceType.JIRA, "jira"),
            ("pardot", ExternalDataSourceType.PARDOT, "pardot"),
            ("twilio", ExternalDataSourceType.TWILIO, "twilio"),
            ("vercel", ExternalDataSourceType.VERCEL, "vercel"),
        ]
    )
    def test_catalogue_kind_accepts_the_derived_auth_type_of_its_source(
        self, _name: str, source_type: ExternalDataSourceType, kind: str
    ) -> None:
        assert typed_in_auth_type(source_type.value) == AuthType.CREDENTIALS
        assert AuthType.CREDENTIALS in kind_auth_types(kind).supported

        pk = self._create(self._source(source_type), {"api_key": "fake-key"})

        assert (_row(pk).kind, _row(pk).auth_type) == (kind, "credentials")

    @parameterized.expand(
        [
            # A typed-in row on a kind with an OAuth default is invisible to code that did not ask for it.
            ("stripe_token", ExternalDataSourceType.STRIPE, STRIPE_FIELDS, "stripe", False),
            ("github_token", ExternalDataSourceType.GITHUB, {"auth_method": {"selection": "pat"}}, "github", False),
            # A row with the default auth type of its kind: the unqualified manager skips it for its marker.
            ("postgres_credentials", ExternalDataSourceType.POSTGRES, PG_FIELDS, "postgresql", False),
        ]
    )
    def test_named_accessors_skip_source_rows(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        fields: dict[str, Any],
        kind: str,
        visible_unqualified: bool,
    ) -> None:
        pk = self._create(self._source(source_type), fields)

        assert Integration.objects.filter(id=pk).exists() == visible_unqualified
        assert IntegrationManager.kinds(kind).get_many(self.team.id, [pk]) == {}
        assert list(IntegrationManager.source(kind).any.get_many(self.team.id, [pk])) == [pk]
        assert list(IntegrationManager.any.with_source_rows().get_many(self.team.id, [pk])) == [pk]

    @parameterized.expand(
        [
            ("oauth_only_source", ExternalDataSourceType.HUBSPOT, ValueError),
            ("custom_has_no_kind", ExternalDataSourceType.CUSTOM, UnknownCredentialKindError),
        ]
    )
    def test_source_without_a_typed_in_auth_type_gets_no_row(
        self, _name: str, source_type: ExternalDataSourceType, error: type[Exception]
    ) -> None:
        source = self._source(source_type)

        with self.assertRaises(error):
            WarehouseSourceCredentialsStore.create(source, {"token": "fake"})
        assert source.credentials_integration_id is None
        assert not Integration.objects._with_auth(AuthTypeSelector.ANY).filter(team_id=self.team.pk).exists()
        source.credentials_integration_id = "1"
        assert WarehouseSourceCredentialsStore.get(source) is None
        assert WarehouseSourceCredentialsStore.release(source) is False

    @parameterized.expand(
        [
            ("none", lambda store_pk, other: None),
            ("not_a_number", lambda store_pk, other: "abc"),
            ("missing_pk", lambda store_pk, other: str(store_pk + 1000)),
            ("other_team", lambda store_pk, other: str(other["other_team"])),
            ("other_kind", lambda store_pk, other: str(other["stripe"])),
            ("unmarked_row_of_same_kind", lambda store_pk, other: str(other["native_postgres"])),
            # The credentials service is not readable yet, so a UUID resolves to no row.
            ("uuid", lambda store_pk, other: str(uuid4())),
            # Only the canonical form of the reference counts, so a bad write never reads another row.
            ("leading_zero", lambda store_pk, other: f"0{store_pk}"),
            ("whitespace", lambda store_pk, other: f" {store_pk}"),
            ("signed", lambda store_pk, other: f"+{store_pk}"),
            ("uuid_upper_case", lambda store_pk, other: str(uuid4()).upper()),
            ("empty", lambda store_pk, other: ""),
        ]
    )
    def test_a_reference_the_source_cannot_use_is_no_row(self, _name: str, ref_of: Any) -> None:
        source = self._source()
        store_pk = self._create(source, PG_FIELDS)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other = {
            "other_team": self._create(self._source(team=other_team), PG_FIELDS),
            "stripe": self._create(self._source(ExternalDataSourceType.STRIPE), STRIPE_FIELDS),
            "native_postgres": IntegrationManager.postgresql.credentials.create(
                self.team.id, external_id="native", config={}, sensitive_config={"fields": PG_FIELDS}
            ).id,
        }

        source.credentials_integration_id = ref_of(store_pk, other)

        assert WarehouseSourceCredentialsStore.get(source) is None
        assert WarehouseSourceCredentialsStore.get_many([source]) == {}
        assert WarehouseSourceCredentialsStore.release(source) is False
        with self.assertRaises(CredentialsNotFoundError):
            WarehouseSourceCredentialsStore.update(source, {**PG_FIELDS, "password": "new"})
        assert self._fields_of_row(store_pk) == PG_FIELDS

    @parameterized.expand(
        [("empty_dict", {}), ("no_fields_key", {"other": 1}), ("fields_not_a_mapping", {"fields": 5})]
    )
    def test_unreadable_row_is_reported_distinctly(self, _name: str, stored: dict[str, Any]) -> None:
        source = self._source()
        pk = self._create(source, PG_FIELDS)
        row = _row(pk)
        row.sensitive_config = stored
        row.save()

        with self.assertRaises(CredentialsUnreadableError) as raised:
            WarehouseSourceCredentialsStore.get(source)
        assert "fake-password" not in str(raised.exception)
        assert WarehouseSourceCredentialsStore.get_many([source]) == {source.id: CredentialsUnreadable()}

    def test_undecryptable_leaf_is_unreadable_and_extra_layers_are_peeled(self) -> None:
        source, double_encrypted = self._source(), self._source()
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
        foreign_ciphertext = Fernet(Fernet.generate_key()).encrypt(b"fake-password").decode()
        self._create(source, {"host": "db.example.com", "password": foreign_ciphertext})
        self._create(double_encrypted, {"password": field.encrypt("fake-password")})

        with self.assertRaises(CredentialsUnreadableError):
            WarehouseSourceCredentialsStore.get(source)
        assert WarehouseSourceCredentialsStore.get(double_encrypted) == {"password": "fake-password"}
        assert WarehouseSourceCredentialsStore.get_many([source, double_encrypted]) == {
            source.id: CredentialsUnreadable(),
            double_encrypted.id: {"password": "fake-password"},
        }

    def test_get_many_uses_one_query_per_team_and_source_type_and_skips_rows_a_source_cannot_use(self) -> None:
        postgres, postgres_b, stripe, without_ref, wrong_kind, uuid_ref = (
            self._source(),
            self._source(),
            self._source(ExternalDataSourceType.STRIPE),
            self._source(),
            self._source(),
            self._source(),
        )
        self._create(postgres, PG_FIELDS)
        self._create(postgres_b, {**PG_FIELDS, "host": "b.example.com"})
        wrong_kind.credentials_integration_id = str(self._create(stripe, STRIPE_FIELDS))
        uuid_ref.credentials_integration_id = str(uuid4())

        with self.assertNumQueries(2):
            result = WarehouseSourceCredentialsStore.get_many(
                [postgres, postgres_b, stripe, without_ref, wrong_kind, uuid_ref]
            )

        assert result == {
            postgres.id: PG_FIELDS,
            postgres_b.id: {**PG_FIELDS, "host": "b.example.com"},
            stripe.id: STRIPE_FIELDS,
        }

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
            # A write that changes no stored value needs no confirmation.
            ("shared_same_fields_as_strings", "source", {**PG_FIELDS, "port": 5432}, False, "in_place"),
            ("shared_unset_optional_field", "source", {**PG_FIELDS, "database": None}, False, "in_place"),
        ]
    )
    def test_update_of_a_shared_row_needs_confirmation_or_makes_a_new_row(
        self, _name: str, other_user: str | None, new_fields: dict[str, Any], allow_shared: bool, outcome: str
    ) -> None:
        source = self._source()
        pk = self._create(source, PG_FIELDS)
        if other_user == "source":
            self._referencing(pk)
        workflows = (
            [WorkflowSummary(id="wf1", name="Nightly sync", status="active")] if other_user == "workflow" else []
        )

        with patch(
            "products.workflows.backend.integration_usages.get_active_workflows_using_integration",
            return_value=workflows,
        ):
            if outcome == "conflict":
                with self.assertRaises(SharedCredentialsError) as raised:
                    WarehouseSourceCredentialsStore.update(source, new_fields, allow_shared=allow_shared)
                assert raised.exception.integration_id == pk
                assert [usage.type for usage in raised.exception.usages] == [
                    "workflow" if other_user == "workflow" else "warehouse_source"
                ]
                assert source.credentials_integration_id == str(pk)
                assert WarehouseSourceCredentialsStore.get(source) == PG_FIELDS
                return
            reference = WarehouseSourceCredentialsStore.update(source, new_fields, allow_shared=allow_shared)

        new_pk = reference.legacy_id
        assert new_pk is not None
        assert source.credentials_integration_id == str(new_pk)
        if outcome == "in_place":
            assert new_pk == pk
        else:
            assert new_pk != pk
            assert self._fields_of_row(pk) == PG_FIELDS
            # The source points at the new row only when the caller saves it with its inputs.
            assert ExternalDataSource.objects.get(id=source.id).credentials_integration_id == str(pk)
        assert WarehouseSourceCredentialsStore.get(source) == {
            key: str(value) if key == "port" else value for key, value in new_fields.items() if value is not None
        }
        assert _row(new_pk).config[WAREHOUSE_SOURCE_TYPE_CONFIG_KEY] == "Postgres"

    @parameterized.expand(
        [
            # (name, source type, fields, changed path, new value, outcome)
            ("nested_user", ExternalDataSourceType.SNOWFLAKE, SNOWFLAKE_FIELDS, "auth_type.user", "writer", "new_row"),
            (
                "nested_secret",
                ExternalDataSourceType.SNOWFLAKE,
                SNOWFLAKE_FIELDS,
                "auth_type.password",
                "new",
                "conflict",
            ),
            (
                "url_password",
                ExternalDataSourceType.POSTGRES,
                PG_URL_FIELDS,
                "connection_string",
                "postgresql://reader:new@db.example.com:5432/app?sslmode=require",
                "conflict",
            ),
            (
                "url_query",
                ExternalDataSourceType.POSTGRES,
                PG_URL_FIELDS,
                "connection_string",
                "postgresql://reader:fake-password@db.example.com:5432/app?sslmode=disable",
                "conflict",
            ),
            (
                "url_host",
                ExternalDataSourceType.POSTGRES,
                PG_URL_FIELDS,
                "connection_string",
                "postgresql://reader:fake-password@other.example.com:5432/app",
                "new_row",
            ),
            (
                "url_database",
                ExternalDataSourceType.POSTGRES,
                PG_URL_FIELDS,
                "connection_string",
                "postgresql://reader:fake-password@db.example.com:5432/other",
                "new_row",
            ),
            (
                "mongodb_auth_source",
                ExternalDataSourceType.MONGODB,
                {"connection_string": "mongodb://reader:fake-password@db.example.com/app?authSource=admin"},
                "connection_string",
                "mongodb://reader:fake-password@db.example.com/app?authSource=other",
                "new_row",
            ),
            (
                "mongodb_default_auth_source",
                ExternalDataSourceType.MONGODB,
                {"connection_string": "mongodb://reader:fake-password@db.example.com/app"},
                "connection_string",
                "mongodb://reader:fake-password@db.example.com/app?authSource=other",
                "new_row",
            ),
            (
                "mongodb_no_path_auth_source",
                ExternalDataSourceType.MONGODB,
                {"connection_string": "mongodb+srv://reader:fake-password@db.example.com?authSource=admin"},
                "connection_string",
                "mongodb+srv://reader:fake-password@db.example.com?authSource=other",
                "new_row",
            ),
            (
                "mongodb_password",
                ExternalDataSourceType.MONGODB,
                {"connection_string": "mongodb://reader:fake-password@db.example.com/app?authSource=admin"},
                "connection_string",
                "mongodb://reader:new@db.example.com/app?authSource=admin",
                "conflict",
            ),
            (
                "pairs_password",
                ExternalDataSourceType.MSSQL,
                MSSQL_ADO_FIELDS,
                "connection_string",
                "Server=db.example.com,1433;User Id=reader;Password=new;Database=app",
                "conflict",
            ),
            (
                "pairs_user",
                ExternalDataSourceType.MSSQL,
                MSSQL_ADO_FIELDS,
                "connection_string",
                "Server=db.example.com,1433;User Id=writer;Password=fake-password;Database=app",
                "new_row",
            ),
            (
                "tunnel_key",
                ExternalDataSourceType.POSTGRES,
                PG_TUNNEL_FIELDS,
                "ssh_tunnel.auth_type.private_key",
                "new",
                "conflict",
            ),
            (
                "tunnel_passphrase",
                ExternalDataSourceType.POSTGRES,
                PG_TUNNEL_FIELDS,
                "ssh_tunnel.auth_type.passphrase",
                "new",
                "conflict",
            ),
            (
                "tunnel_username",
                ExternalDataSourceType.POSTGRES,
                PG_TUNNEL_FIELDS,
                "ssh_tunnel.auth_type.username",
                "other",
                "new_row",
            ),
            (
                "tunnel_host",
                ExternalDataSourceType.POSTGRES,
                PG_TUNNEL_FIELDS,
                "ssh_tunnel.host",
                "other.example.com",
                "new_row",
            ),
            (
                "tunnel_enabled_case",
                ExternalDataSourceType.POSTGRES,
                PG_TUNNEL_FIELDS,
                "ssh_tunnel.enabled",
                "true",
                "conflict",
            ),
        ]
    )
    def test_shared_row_identity_reads_nested_fields_and_ignores_secrets(
        self,
        _name: str,
        source_type: ExternalDataSourceType,
        fields: dict[str, Any],
        path: str,
        value: Any,
        outcome: str,
    ) -> None:
        source = self._source(source_type)
        pk = self._create(source, fields)
        self._referencing(pk, source_type)
        new_fields = _with(fields, path, value)

        if outcome == "conflict":
            with self.assertRaises(SharedCredentialsError):
                WarehouseSourceCredentialsStore.update(source, new_fields)
            assert WarehouseSourceCredentialsStore.get(source) == fields
            return
        new_pk = WarehouseSourceCredentialsStore.update(source, new_fields).legacy_id
        assert new_pk is not None and new_pk != pk
        assert self._fields_of_row(pk, source_type) == fields
        assert WarehouseSourceCredentialsStore.get(source) == new_fields

    def test_update_of_a_row_of_another_kind_raises(self) -> None:
        stripe = self._source(ExternalDataSourceType.STRIPE)
        stripe_pk = self._create(stripe, STRIPE_FIELDS)
        postgres = self._source()
        postgres.credentials_integration_id = str(stripe_pk)

        with self.assertRaises(CredentialsNotFoundError):
            WarehouseSourceCredentialsStore.update(postgres, PG_FIELDS)
        assert WarehouseSourceCredentialsStore.get(stripe) == STRIPE_FIELDS

    @parameterized.expand(
        [
            ("orphan", False, True),
            ("still_used_by_another_source", True, False),
        ]
    )
    def test_release_never_deletes_the_row(self, _name: str, shared: bool, orphaned: bool) -> None:
        source = self._source()
        pk = self._create(source, PG_FIELDS)
        if shared:
            self._referencing(pk)

        assert WarehouseSourceCredentialsStore.release(source) is orphaned
        assert IntegrationManager.source("postgresql").credentials.get(self.team.id, pk).id == pk

    def test_release_of_a_reference_the_source_cannot_use_is_a_no_op(self) -> None:
        source = self._source()
        oauth_row = IntegrationManager.hubspot.oauth.create(self.team.id, external_id="H1", config={})

        source.credentials_integration_id = str(oauth_row.id)
        assert WarehouseSourceCredentialsStore.release(source) is False
        source.credentials_integration_id = None
        assert WarehouseSourceCredentialsStore.release(source) is False

    @parameterized.expand(
        [
            ("unused", False, 0),
            ("still_used_by_another_source", True, 1),
        ]
    )
    def test_discard_created_deletes_the_source_and_its_unused_row(
        self, _name: str, shared: bool, rows_left: int
    ) -> None:
        source = self._source()
        source_pk = source.pk
        pk = self._create(source, PG_FIELDS)
        if shared:
            self._referencing(pk)

        SourceInputsStore.discard_created(source)

        assert not ExternalDataSource.objects.filter(pk=source_pk).exists()
        assert len(IntegrationManager.source("postgresql").credentials.list(self.team.id)) == rows_left

    def test_discard_created_keeps_a_row_out_of_the_store_scope(self) -> None:
        source = self._source()
        oauth_row = IntegrationManager.hubspot.oauth.create(self.team.id, external_id="H1", config={})
        source.credentials_integration_id = str(oauth_row.id)
        source.save()

        SourceInputsStore.discard_created(source)

        assert IntegrationManager.hubspot.oauth.get(self.team.id, oauth_row.id).id == oauth_row.id

    @patch("products.warehouse_sources.backend.models.external_data_source.capture_exception")
    def test_soft_delete_keeps_the_row_and_survives_store_failure(self, capture: Any) -> None:
        deleted, failing, without_row = self._source(), self._source(), self._source()
        for source in (deleted, failing):
            self._create(source, PG_FIELDS)

        with patch.object(
            WarehouseSourceCredentialsStore, "release", wraps=WarehouseSourceCredentialsStore.release
        ) as release:
            deleted.soft_delete()
            without_row.soft_delete()
        release.assert_called_once_with(deleted)
        assert len(IntegrationManager.source("postgresql").any.list(self.team.id)) == 2

        with patch.object(WarehouseSourceCredentialsStore, "release", side_effect=RuntimeError("boom")):
            failing.soft_delete()
        failing.refresh_from_db()
        assert failing.deleted is True
        capture.assert_called_once()

    @parameterized.expand(
        [
            ("top_level_int", {"linear_integration_id": 7}, True),
            ("top_level_string", {"linear_integration_id": "7"}, True),
            ("nested", {"auth": {"hubspot_integration_id": 7}}, True),
            # The typed-in pointer lives in the column, so a stale input of the same name is not a pointer.
            ("column_name_in_inputs", {"credentials_integration_id": "7"}, False),
            ("other_integration", {"linear_integration_id": 8}, False),
            ("not_a_pointer_key", {"workspace_id": 7}, False),
            ("no_inputs", None, False),
        ]
    )
    def test_reference_detection_in_inputs(self, _name: str, inputs: dict[str, Any] | None, expected: bool) -> None:
        source = self._source()
        source.job_inputs = inputs
        source.save()

        found = list_sources_using_integration(self.team.id, 7)

        assert [ref.id for ref in found] == ([source.id] if expected else [])

    @parameterized.expand(
        [
            ("column", "7", None, False, True),
            ("column_and_inputs_count_once", "7", {"linear_integration_id": "7"}, False, True),
            ("deleted_source", "7", None, True, False),
            ("other_row", "8", None, False, False),
            ("leading_zero", "07", None, False, False),
            ("uuid", "0b7e8c3a-5f4d-4e2a-9c1b-2d3e4f5a6b7c", None, False, False),
        ]
    )
    def test_reference_detection_by_column(
        self, _name: str, column: str, inputs: dict[str, Any] | None, deleted: bool, expected: bool
    ) -> None:
        source = self._source()
        source.credentials_integration_id = column
        source.job_inputs = inputs
        source.deleted = deleted
        source.save()

        found = list_sources_using_integration(self.team.id, 7)

        assert [(ref.id, ref.unreadable) for ref in found] == ([(source.id, False)] if expected else [])

    @parameterized.expand(
        [
            # (name, row, broken source type, encrypted pointer, counted)
            ("oauth_row_of_its_kind", "oauth", ExternalDataSourceType.HUBSPOT, False, True),
            ("oauth_row_of_its_kind_encrypted_pointer", "oauth", ExternalDataSourceType.HUBSPOT, True, True),
            ("oauth_row_of_another_kind", "oauth", ExternalDataSourceType.POSTGRES, False, False),
            # The typed-in pointer is in the column, which always reads, so broken inputs say nothing about it.
            ("typed_in_row_of_its_kind", "typed_in", ExternalDataSourceType.POSTGRES, False, False),
            ("typed_in_row_of_its_kind_encrypted_pointer", "typed_in", ExternalDataSourceType.POSTGRES, True, False),
        ]
    )
    def test_a_source_with_unreadable_inputs_counts_as_a_user_of_an_oauth_row_of_its_kind(
        self, _name: str, row: str, broken_type: ExternalDataSourceType, encrypted_pointer: bool, counted: bool
    ) -> None:
        editor = self._source()
        pk = (
            self._create(editor, PG_FIELDS)
            if row == "typed_in"
            else IntegrationManager.hubspot.oauth.create(self.team.id, external_id="H1", config={}).id
        )
        broken = self._source(broken_type)
        broken.job_inputs = (
            {"auth": {"hubspot_integration_id": Fernet(Fernet.generate_key()).encrypt(str(pk).encode()).decode()}}
            if encrypted_pointer
            else "not json"
        )
        broken.save()

        found = list_sources_using_integration(self.team.id, pk)

        expected = [(broken.id, True)] if counted else []
        if row == "typed_in":
            expected = [(editor.id, False)]
            assert WarehouseSourceCredentialsStore.update(editor, {**PG_FIELDS, "password": "new"}).legacy_id == pk
        assert [(ref.id, ref.unreadable) for ref in found] == expected
        # Such a user blocks a delete of the row, with its own usage type.
        assert [usage.type for usage in integration_usages(self.team.id, pk) if usage.id == str(broken.id)] == (
            ["unreadable_warehouse_source"] if counted else []
        )

    def test_conflict_response_names_the_other_users(self) -> None:
        source = self._source()
        pk = self._create(source, PG_FIELDS)
        self._referencing(pk)
        with self.assertRaises(SharedCredentialsError) as raised:
            WarehouseSourceCredentialsStore.update(source, {**PG_FIELDS, "password": "new"})

        response = shared_credentials_conflict_response(raised.exception)

        assert response.status_code == 409
        assert response.data["code"] == "shared_credentials"
        assert response.data["integration_id"] == pk
        assert [usage["type"] for usage in response.data["usages"]] == ["warehouse_source"]
        assert "update_shared_credentials=true" in response.data["detail"]


class TestWarehouseSourceUsageProvider(BaseTest):
    def _source(
        self,
        job_inputs: dict[str, Any],
        prefix: str | None = None,
        deleted: bool = False,
        credentials_integration_id: str | None = None,
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team=self.team,
            source_id=str(uuid4()),
            connection_id=str(uuid4()),
            status="Completed",
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs=job_inputs,
            prefix=prefix,
            deleted=deleted,
            credentials_integration_id=credentials_integration_id,
        )

    def _row(self) -> IntegrationRecord:
        return IntegrationManager.source("postgresql").credentials.create(
            self.team.id, external_id="pg", config={WAREHOUSE_SOURCE_TYPE_CONFIG_KEY: "Postgres"}
        )

    @parameterized.expand(
        [
            ("credentials_column", None, "prod", "Postgres (prod)"),
            ("oauth_pointer_without_prefix", "linear_integration_id", None, "Postgres"),
        ]
    )
    def test_the_sdk_reports_a_source_that_points_at_the_row(
        self, _name: str, inputs_key: str | None, prefix: str | None, name: str
    ) -> None:
        row = self._row()
        pointer: dict[str, Any] = (
            {"job_inputs": {inputs_key: str(row.id)}}
            if inputs_key
            else {"job_inputs": {}, "credentials_integration_id": str(row.id)}
        )
        source = self._source(prefix=prefix, **pointer)
        self._source(deleted=True, **pointer)

        assert IntegrationManager.any.with_source_rows().usages(self.team.id, row.id) == [
            IntegrationUsage(type="warehouse_source", id=str(source.id), name=name)
        ]

    def test_delete_of_a_used_row_raises_and_keeps_the_row(self) -> None:
        row = self._row()
        self._source({}, credentials_integration_id=str(row.id))

        with self.assertRaises(IntegrationInUse) as raised:
            IntegrationManager.source("postgresql").any.delete(self.team.id, row.id)

        assert [usage.type for usage in raised.exception.usages] == ["warehouse_source"]
        assert IntegrationManager.any.with_source_rows().get(self.team.id, row.id).id == row.id


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
    def test_every_typed_in_source_type_has_an_auth_type_its_kind_supports(self) -> None:
        source_types = _typed_in_source_types()
        assert len(source_types) > 800

        for source_type in source_types:
            auth_type = typed_in_auth_type(source_type)
            assert auth_type in kind_auth_types(CREDENTIAL_KINDS[source_type]).supported, source_type

    def test_every_credential_kind_is_a_valid_stored_kind(self) -> None:
        stored_kinds = {value for value, _ in integration_kind_choices()}
        known = catalogued_kinds()

        for kind in set(CREDENTIAL_KINDS.values()):
            assert kind in stored_kinds, kind
            assert kind in known, kind

    @parameterized.expand(
        [
            ("oauth_only_source", ExternalDataSourceType.LINEAR, ValueError),
            ("custom_has_no_kind", ExternalDataSourceType.CUSTOM, UnknownCredentialKindError),
        ]
    )
    def test_typed_in_auth_type_rejects_a_source_without_typed_in_credentials(
        self, _name: str, source_type: ExternalDataSourceType, error: type[Exception]
    ) -> None:
        with self.assertRaises(error):
            typed_in_auth_type(source_type.value)


class TestCredentialIdentityFields(SimpleTestCase):
    @parameterized.expand(
        [
            ("postgres", ExternalDataSourceType.POSTGRES, {"connection_string", "host", "port", "ssh_tunnel", "user"}),
            (
                "supabase_inherits",
                ExternalDataSourceType.SUPABASE,
                {"connection_string", "host", "port", "ssh_tunnel", "user"},
            ),
            ("mysql", ExternalDataSourceType.MYSQL, {"host", "port", "ssh_tunnel", "user"}),
            ("snowflake_nested_user", ExternalDataSourceType.SNOWFLAKE, {"account_id", "connection_string", "user"}),
            ("trino_nested_user", ExternalDataSourceType.TRINO, {"host", "port", "user"}),
            ("mongodb", ExternalDataSourceType.MONGODB, {"connection_string"}),
            ("twilio_account", ExternalDataSourceType.TWILIO, {"account_sid"}),
            ("okta_host_field", ExternalDataSourceType.OKTA, {"okta_domain"}),
            ("freshservice_host_field", ExternalDataSourceType.FRESHSERVICE, {"domain"}),
            ("hatchet_host_field", ExternalDataSourceType.HATCHET, {"host"}),
            ("stripe_none", ExternalDataSourceType.STRIPE, set()),
            ("zendesk_none", ExternalDataSourceType.ZENDESK, set()),
            ("custom_none", ExternalDataSourceType.CUSTOM, set()),
        ]
    )
    def test_identity_fields_match_the_old_rule(
        self, _name: str, source_type: ExternalDataSourceType, expected: set[str]
    ) -> None:
        assert SourceRegistry.get_source(source_type).credential_identity_fields == expected
