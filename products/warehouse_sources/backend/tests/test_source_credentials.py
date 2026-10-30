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

from products.warehouse_sources.backend.facade.contracts import CREDENTIALS_REFERENCE_KEY, SharedCredentialsError
from products.warehouse_sources.backend.facade.credential_kinds import CREDENTIAL_KINDS
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
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.presentation.views.external_data_source.shared_credentials import (
    shared_credentials_conflict_response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_input_classification import (
    CLASSIFICATION_AUDIT_PATH,
    JobInputKind,
    classify_job_input_key,
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

    def _referencing(self, ref: int, source_type: ExternalDataSourceType = ExternalDataSourceType.POSTGRES) -> None:
        source = self._source(source_type)
        source.job_inputs = {CREDENTIALS_REFERENCE_KEY: str(ref)}
        source.save()

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

        pk = WarehouseSourceCredentialsStore.create(source, fields)

        row = IntegrationManager.source(kind).any.get(self.team.id, pk)
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

        pk = WarehouseSourceCredentialsStore.create(self._source(source_type), {"api_key": "fake-key"})

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
        pk = WarehouseSourceCredentialsStore.create(self._source(source_type), fields)

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
        assert not Integration.objects._with_auth(AuthTypeSelector.ANY).filter(team_id=self.team.pk).exists()
        assert WarehouseSourceCredentialsStore.get(source, 1) is None
        assert WarehouseSourceCredentialsStore.release(source, 1) is False

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
                self._source(ExternalDataSourceType.STRIPE), STRIPE_FIELDS
            ),
            "native_postgres": IntegrationManager.postgresql.credentials.create(
                self.team.id, external_id="native", config={}, sensitive_config={"fields": PG_FIELDS}
            ).id,
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
        row = _row(pk)
        row.sensitive_config = stored
        row.save()

        with self.assertRaises(CredentialsUnreadableError) as raised:
            WarehouseSourceCredentialsStore.get(source, pk)
        assert "fake-password" not in str(raised.exception)
        assert WarehouseSourceCredentialsStore.get_many([(source, pk)]) == {source.id: CredentialsUnreadable()}

    def test_undecryptable_leaf_is_unreadable_and_extra_layers_are_peeled(self) -> None:
        source, double_encrypted = self._source(), self._source()
        field = cast(EncryptedJSONField, Integration._meta.get_field("sensitive_config"))
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

    def test_get_many_uses_one_query_per_team_and_source_type_and_skips_rows_a_source_cannot_use(self) -> None:
        postgres, postgres_b, stripe, without_ref, wrong_kind = (
            self._source(),
            self._source(),
            self._source(ExternalDataSourceType.STRIPE),
            self._source(),
            self._source(),
        )
        postgres_pk = WarehouseSourceCredentialsStore.create(postgres, PG_FIELDS)
        postgres_b_pk = WarehouseSourceCredentialsStore.create(postgres_b, {**PG_FIELDS, "host": "b.example.com"})
        stripe_pk = WarehouseSourceCredentialsStore.create(stripe, STRIPE_FIELDS)

        with self.assertNumQueries(2):
            result = WarehouseSourceCredentialsStore.get_many(
                [
                    (postgres, postgres_pk),
                    (postgres_b, postgres_b_pk),
                    (stripe, stripe_pk),
                    (without_ref, None),
                    (wrong_kind, stripe_pk),
                ]
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
        pk = WarehouseSourceCredentialsStore.create(source, PG_FIELDS)
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
        pk = WarehouseSourceCredentialsStore.create(source, fields)
        self._referencing(pk, source_type)
        new_fields = _with(fields, path, value)

        if outcome == "conflict":
            with self.assertRaises(SharedCredentialsError):
                WarehouseSourceCredentialsStore.update(source, pk, new_fields)
            assert WarehouseSourceCredentialsStore.get(source, pk) == fields
            return
        new_pk = WarehouseSourceCredentialsStore.update(source, pk, new_fields)
        assert new_pk != pk
        assert WarehouseSourceCredentialsStore.get(source, pk) == fields
        assert WarehouseSourceCredentialsStore.get(source, new_pk) == new_fields

    @parameterized.expand(
        [
            ("missing_row", lambda other: 12345),
            ("row_of_another_kind", lambda other: other),
        ]
    )
    def test_update_of_a_row_the_source_cannot_use_raises(self, _name: str, ref_of: Any) -> None:
        stripe = self._source(ExternalDataSourceType.STRIPE)
        stripe_pk = WarehouseSourceCredentialsStore.create(stripe, STRIPE_FIELDS)

        with self.assertRaises(CredentialsNotFoundError):
            WarehouseSourceCredentialsStore.update(self._source(), ref_of(stripe_pk), PG_FIELDS)
        assert WarehouseSourceCredentialsStore.get(stripe, stripe_pk) == STRIPE_FIELDS

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
        assert IntegrationManager.source("postgresql").credentials.get(self.team.id, pk).id == pk

    def test_release_of_a_reference_the_source_cannot_use_is_a_no_op(self) -> None:
        source = self._source()
        oauth_row = IntegrationManager.hubspot.oauth.create(self.team.id, external_id="H1", config={})

        assert WarehouseSourceCredentialsStore.release(source, oauth_row.id) is False
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

    @parameterized.expand(
        [
            ("same_kind", ExternalDataSourceType.POSTGRES, True, False),
            ("other_kind", ExternalDataSourceType.STRIPE, False, False),
            ("encrypted_pointer_same_kind", ExternalDataSourceType.POSTGRES, True, True),
            ("encrypted_pointer_other_kind", ExternalDataSourceType.STRIPE, False, True),
        ]
    )
    def test_a_source_with_unreadable_inputs_blocks_a_delete_of_a_row_of_its_kind_but_not_an_edit(
        self, _name: str, broken_type: ExternalDataSourceType, counted: bool, encrypted_pointer: bool
    ) -> None:
        editor = self._source()
        pk = WarehouseSourceCredentialsStore.create(editor, PG_FIELDS)
        broken = self._source(broken_type)
        broken.job_inputs = (
            {"auth": {CREDENTIALS_REFERENCE_KEY: Fernet(Fernet.generate_key()).encrypt(str(pk).encode()).decode()}}
            if encrypted_pointer
            else "not json"
        )
        broken.save()
        new_fields = {**PG_FIELDS, "password": "new"}

        assert WarehouseSourceCredentialsStore.update(editor, pk, new_fields) == pk
        assert WarehouseSourceCredentialsStore.get(editor, pk) == new_fields
        assert IntegrationManager.any.with_source_rows().usages(self.team.id, pk) == (
            [IntegrationUsage(type="unreadable_warehouse_source", id=str(broken.id), name="Postgres")]
            if counted
            else []
        )

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


class TestWarehouseSourceUsageProvider(BaseTest):
    def _source(
        self, job_inputs: dict[str, Any], prefix: str | None = None, deleted: bool = False
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
        )

    def _row(self) -> IntegrationRecord:
        return IntegrationManager.source("postgresql").credentials.create(
            self.team.id, external_id="pg", config={WAREHOUSE_SOURCE_TYPE_CONFIG_KEY: "Postgres"}
        )

    @parameterized.expand(
        [
            ("credentials_reference", CREDENTIALS_REFERENCE_KEY, "prod", "Postgres (prod)"),
            ("oauth_pointer_without_prefix", "linear_integration_id", None, "Postgres"),
        ]
    )
    def test_the_sdk_reports_a_source_that_points_at_the_row(
        self, _name: str, key: str, prefix: str | None, name: str
    ) -> None:
        row = self._row()
        source = self._source({key: str(row.id)}, prefix=prefix)
        self._source({key: str(row.id)}, deleted=True)

        assert IntegrationManager.any.with_source_rows().usages(self.team.id, row.id) == [
            IntegrationUsage(type="warehouse_source", id=str(source.id), name=name)
        ]

    def test_delete_of_a_used_row_raises_and_keeps_the_row(self) -> None:
        row = self._row()
        self._source({CREDENTIALS_REFERENCE_KEY: str(row.id)})

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

    @parameterized.expand(
        [
            ("postgres", ExternalDataSourceType.POSTGRES),
            ("stripe_select_reference_source", ExternalDataSourceType.STRIPE),
            ("generated_kind", ExternalDataSourceType.ABLY),
        ]
    )
    def test_credentials_reference_key_is_a_reference(self, _name: str, source_type: ExternalDataSourceType) -> None:
        assert classify_job_input_key(source_type, CREDENTIALS_REFERENCE_KEY, "12") == JobInputKind.REFERENCE


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
