import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.integrations import IntegrationManager, IntegrationReference
from posthog.models import Team
from posthog.models.integration import ANY, Integration

from products.warehouse_sources.backend.facade.contracts import (
    CONNECTION_FIELDS_STRIPPED_KEY,
    CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY,
    CREDENTIALS_REFERENCE_INPUT_KEY,
    SharedCredentialsEdit,
    SharedCredentialsError,
    SourceCredentialsMissingError,
    UnusableCredentialsReferenceError,
)
from products.warehouse_sources.backend.logic import source_credentials_rollout as rollout
from products.warehouse_sources.backend.logic.source_credentials import WarehouseSourceCredentialsStore
from products.warehouse_sources.backend.logic.source_inputs import (
    INPUTS_UPDATE_FIELDS,
    SourceInputsStore,
    UnreadableSourceInputsError,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

# These tests check the stored credentials, so raw saves keep their inputs as they are.
pytestmark = pytest.mark.raw_warehouse_source_credentials


POSTGRES_INPUTS: dict[str, Any] = {
    "host": "db.example.com",
    "port": 5432,
    "database": "app",
    "user": "reader",
    "password": "fake-password",
    "schema": "public",
    "cdc_enabled": True,
    "cdc_slot_name": "posthog_slot",
}


def _source(source_type: str = ExternalDataSourceType.POSTGRES, job_inputs: Any = None) -> ExternalDataSource:
    return ExternalDataSource(team_id=1, source_type=source_type, job_inputs=job_inputs)


class TestSourceInputsStoreReads(SimpleTestCase):
    @parameterized.expand(
        [
            ("none", None, {}),
            ("empty", {}, {}),
            ("mapping", {"schema": "s", "cdc_enabled": True}, {"schema": "s", "cdc_enabled": True}),
            ("json_string", json.dumps({"schema": "s"}), {"schema": "s"}),
        ]
    )
    def test_load_returns_a_mapping(self, _name: str, stored: Any, expected: dict[str, Any]) -> None:
        assert SourceInputsStore.load(_source(job_inputs=stored)) == expected

    @parameterized.expand(
        [
            ("list", ["not", "a", "mapping"]),
            ("not_json", "fake-password"),
            ("blank_string", ""),
            ("json_list", json.dumps(["a"])),
        ]
    )
    def test_load_raises_without_the_value(self, _name: str, stored: Any) -> None:
        with self.assertRaises(UnreadableSourceInputsError) as raised:
            SourceInputsStore.load(_source(job_inputs=stored))
        assert "fake-password" not in str(raised.exception)

    def test_load_returns_a_copy(self) -> None:
        source = _source(job_inputs={"schema": "s"})
        SourceInputsStore.load(source)["schema"] = "changed"
        assert SourceInputsStore.load(source) == {"schema": "s"}

    def test_load_many_skips_unreadable_sources(self) -> None:
        good = _source(job_inputs={"schema": "s"})
        bad = _source(job_inputs=["not", "a", "mapping"])
        assert SourceInputsStore.load_many([good, bad]) == {good.id: {"schema": "s"}}

    @parameterized.expand(
        [
            (
                "postgres_keeps_schema_and_cdc",
                ExternalDataSourceType.POSTGRES,
                POSTGRES_INPUTS,
                {"schema": "public", "cdc_enabled": True, "cdc_slot_name": "posthog_slot"},
            ),
            (
                "file_upload_keeps_upload_keys",
                ExternalDataSourceType.FILEUPLOAD,
                {"upload_id": "u1", "filename": "a.csv", "file_format": "csv", "schema_name": "a"},
                {"upload_id": "u1", "filename": "a.csv", "file_format": "csv", "schema_name": "a"},
            ),
            (
                "unknown_type_keeps_only_runtime_prefixes",
                "NotARealSource",
                {"schema": "public", "password": "fake-password", "cdc_enabled": True},
                {"cdc_enabled": True},
            ),
        ]
    )
    def test_load_settings_never_returns_connection_fields(
        self, _name: str, source_type: str, stored: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        assert SourceInputsStore.load_settings(_source(source_type, stored)) == expected

    @parameterized.expand(
        [
            ("connection_key", ExternalDataSourceType.POSTGRES, {"password": "x"}, ()),
            ("setting_key", ExternalDataSourceType.POSTGRES, {"schema": "x"}, ()),
            ("removed_connection_key", ExternalDataSourceType.POSTGRES, {}, ("host",)),
            ("upload_key_on_another_source", ExternalDataSourceType.POSTGRES, {"upload_id": "u1"}, ()),
            ("unknown_type", "NotARealSource", {"host": "x"}, ()),
        ]
    )
    def test_update_runtime_rejects_non_runtime_keys(
        self, _name: str, source_type: str, updates: dict[str, Any], remove: tuple[str, ...]
    ) -> None:
        source = _source(source_type, dict(POSTGRES_INPUTS))
        with self.assertRaises(ValueError):
            SourceInputsStore.update_runtime(source, updates, remove=remove)
        assert source.job_inputs == POSTGRES_INPUTS


# EncryptedJSONField stores each leaf as a string, so a database round trip only keeps string values.
STORED_POSTGRES_INPUTS: dict[str, str] = {key: str(value) for key, value in POSTGRES_INPUTS.items()}


class TestSourceInputsStoreWrites(BaseTest):
    def _create(self, inputs: dict[str, Any]) -> ExternalDataSource:
        return SourceInputsStore.create(
            inputs=inputs,
            team_id=self.team.pk,
            source_id="source",
            connection_id="connection",
            status="Running",
            source_type=ExternalDataSourceType.POSTGRES,
        )

    def test_create_then_save_round_trips(self) -> None:
        source = self._create(STORED_POSTGRES_INPUTS)
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == STORED_POSTGRES_INPUTS

        SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))["password"] == "fake-rotated"

    def test_update_runtime_changes_only_the_given_runtime_keys(self) -> None:
        source = self._create(STORED_POSTGRES_INPUTS)

        SourceInputsStore.update_runtime(
            source, {"cdc_consistent_point": "0/16B3748"}, remove=["cdc_slot_name", "cdc_absent_key"]
        )

        expected = {**STORED_POSTGRES_INPUTS, "cdc_consistent_point": "0/16B3748"}
        del expected["cdc_slot_name"]
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == expected

    def test_save_rewrites_a_string_value_as_a_mapping(self) -> None:
        source = self._create({})
        ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=json.dumps({"schema": "s"}))
        source.refresh_from_db()
        assert SourceInputsStore.stored_as_string(source)

        SourceInputsStore.save(source, SourceInputsStore.load(source))

        source.refresh_from_db()
        assert not SourceInputsStore.stored_as_string(source)
        assert SourceInputsStore.load(source) == {"schema": "s"}


POSTGRES_CONNECTION_FIELDS: dict[str, str] = {
    key: STORED_POSTGRES_INPUTS[key] for key in ("host", "port", "database", "user", "password")
}


STORED_POSTGRES_SETTINGS_AND_RUNTIME: dict[str, str] = {
    key: value for key, value in STORED_POSTGRES_INPUTS.items() if key not in POSTGRES_CONNECTION_FIELDS
}
STRIPPED_AT = "2026-01-01T00:00:00+00:00"


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestSourceInputsStoreCredentials(BaseTest):
    def _create(
        self, inputs: dict[str, Any] | None = None, source_type: str = ExternalDataSourceType.POSTGRES
    ) -> ExternalDataSource:
        return SourceInputsStore.create(
            inputs=STORED_POSTGRES_INPUTS if inputs is None else inputs,
            team_id=self.team.pk,
            source_id="source",
            connection_id="connection",
            status="Running",
            source_type=source_type,
        )

    def _raw_source(
        self,
        inputs: dict[str, Any],
        source_type: str = ExternalDataSourceType.POSTGRES,
        column: str | None = None,
    ) -> ExternalDataSource:
        return ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="source",
            connection_id="connection",
            status="Running",
            source_type=source_type,
            job_inputs=inputs,
            credentials_integration_id=column,
        )

    def _rows(self) -> list[Any]:
        return IntegrationManager.source("postgresql").credentials.list(self.team.pk)

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))

    def _shared_sources(self) -> list[ExternalDataSource]:
        first = self._create()
        second = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="other",
            connection_id="other",
            status="Running",
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs=STORED_POSTGRES_INPUTS,
            credentials_integration_id=_column(first),
        )
        return [first, second]

    def _loads(self, source: ExternalDataSource) -> list[Callable[[], dict[str, Any]]]:
        return [
            lambda: SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)),
            lambda: SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)])[source.id],
        ]

    def test_create_makes_a_row_and_later_saves_update_it(self) -> None:
        source = self._create()
        [row] = self._rows()
        assert _column(source) == str(row.id)
        assert self._stored(source) == STORED_POSTGRES_INPUTS
        assert row.config["warehouse_source_type"] == "Postgres"
        assert row.sensitive_config == {"fields": POSTGRES_CONNECTION_FIELDS}

        SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        [updated] = self._rows()
        assert updated.id == row.id
        assert updated.sensitive_config == {"fields": {**POSTGRES_CONNECTION_FIELDS, "password": "fake-rotated"}}
        assert self._stored(source) == {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"}
        assert _column(source) == str(row.id)

    def test_a_failed_insert_leaves_no_row(self) -> None:
        existing = self._create()
        [row] = self._rows()
        with self.assertRaises(IntegrityError):
            SourceInputsStore.create(
                inputs=STORED_POSTGRES_INPUTS,
                id=existing.id,
                team_id=self.team.pk,
                source_id="source",
                connection_id="connection",
                status="Running",
                source_type=ExternalDataSourceType.POSTGRES,
            )

        assert [r.id for r in self._rows()] == [row.id]

    @parameterized.expand(
        [
            ("oauth_only_int", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": 7}, "7"),
            ("oauth_only_string", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": "7"}, "7"),
            ("oauth_only_short_key", ExternalDataSourceType.TIKTOKADS, {"tiktok_integration_id": "7"}, "7"),
            ("oauth_only_without_pointer", ExternalDataSourceType.HUBSPOT, {}, None),
            ("custom_has_no_kind", ExternalDataSourceType.CUSTOM, {"manifest": "{}"}, None),
            (
                "stripe_oauth_option",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}},
                "7",
            ),
            (
                "bigquery_service_account",
                ExternalDataSourceType.BIGQUERY,
                {
                    "auth_type": {"selection": "service_account", "google_cloud_service_account_integration_id": 7},
                    "project_id": "p",
                    "dataset_id": "d",
                },
                "7",
            ),
            # An OAuth pointer wins over typed-in fields next to it, so the source never gets a second row.
            (
                "pardot_oauth_with_typed_in_environment",
                ExternalDataSourceType.PARDOT,
                {"pardot_integration_id": "7", "environment": "sandbox", "business_unit_id": "b"},
                "7",
            ),
            ("slack_legacy_pointer", ExternalDataSourceType.SLACK, {"slack_integration_id": "7"}, "7"),
            # Its OAuth field is in use without a value, so the typed-in `environment` still makes no row.
            (
                "pardot_without_pointer",
                ExternalDataSourceType.PARDOT,
                {"environment": "sandbox", "business_unit_id": "b"},
                None,
            ),
        ]
    )
    def test_an_oauth_source_points_at_its_in_use_oauth_row_and_gets_no_typed_in_row(
        self, _name: str, source_type: str, inputs: dict[str, Any], column: str | None
    ) -> None:
        source = self._create(inputs, source_type=source_type)

        assert IntegrationManager.any.with_source_rows().list(self.team.pk) == []
        assert _column(source) == column

    @parameterized.expand(
        [
            (
                "github_stale_pointer_under_pat",
                ExternalDataSourceType.GITHUB,
                "github",
                {
                    "auth_method": {
                        "selection": "pat",
                        "personal_access_token": "fake-pat",
                        "github_integration_id": "7",
                    },
                    "repository": "posthog/posthog",
                },
            ),
            (
                "slack_token_wins_over_legacy_pointer",
                ExternalDataSourceType.SLACK,
                "slack",
                {"slack_access_token": "fake-token", "slack_integration_id": "7"},
            ),
        ]
    )
    def test_a_stale_oauth_pointer_does_not_hide_typed_in_credentials(
        self, _name: str, source_type: str, kind: str, inputs: dict[str, Any]
    ) -> None:
        source = self._create(inputs, source_type=source_type)

        [row] = IntegrationManager.any.with_source_rows().list(self.team.pk)
        assert row.kind == kind
        assert _column(source) == str(row.id)

    def test_a_shape_the_walk_cannot_read_keeps_the_column(self) -> None:
        source = self._raw_source({}, ExternalDataSourceType.STRIPE, column="7")

        SourceInputsStore.save(source, {"auth_method": "oauth", "stripe_integration_id": "8"})

        assert _column(source) == "7"

    @parameterized.expand([("no_column", None), ("typed_in_column", "999")])
    def test_an_oauth_write_points_the_column_at_the_pointer(self, _name: str, before: str | None) -> None:
        source = self._raw_source({}, ExternalDataSourceType.STRIPE, column=before)

        SourceInputsStore.save(source, {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}})

        assert _column(source) == "7"

    def test_a_switch_from_the_oauth_option_to_typed_in_fields_makes_a_new_row(self) -> None:
        source = self._create(
            {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}},
            source_type=ExternalDataSourceType.STRIPE,
        )
        assert _column(source) == "7"

        SourceInputsStore.save(source, {"auth_method": {"selection": "api_key", "stripe_secret_key": "fake-key"}})

        [row] = IntegrationManager.source("stripe").token.list(self.team.pk)
        assert _column(source) == str(row.id)

    def test_confirmed_edit_of_a_shared_row_changes_the_row(self) -> None:
        first, _second = self._shared_sources()

        first.refresh_from_db()
        SourceInputsStore.assign(
            first,
            {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"},
            shared_credentials=SharedCredentialsEdit.CONFIRMED,
        )
        first.save()

        [row] = self._rows()
        assert row.sensitive_config["fields"]["password"] == "fake-rotated"
        assert self._stored(first)["password"] == "fake-rotated"
        assert _column(first) == str(row.id)

    def test_refused_edit_of_a_shared_row_raises_and_unchanged_fields_do_not(self) -> None:
        first, second = self._shared_sources()
        first.refresh_from_db()

        SourceInputsStore.assign(first, STORED_POSTGRES_INPUTS, shared_credentials=SharedCredentialsEdit.REFUSE)
        with self.assertRaises(SharedCredentialsError) as raised:
            SourceInputsStore.assign(
                first,
                {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"},
                shared_credentials=SharedCredentialsEdit.REFUSE,
            )

        assert [(usage.type, usage.id) for usage in raised.exception.usages] == [("warehouse_source", str(second.id))]
        assert first.credentials_integration_id == _column(second)

    def test_a_host_change_on_a_shared_row_makes_a_new_row(self) -> None:
        first, second = self._shared_sources()
        shared_id = _column(first)
        first.refresh_from_db()

        SourceInputsStore.save(first, {**STORED_POSTGRES_INPUTS, "host": "other.example.com"})

        assert _column(second) == shared_id
        assert _column(first) != shared_id
        assert len(self._rows()) == 2

    def test_a_dangling_reference_gets_a_new_row(self) -> None:
        source = self._create()
        ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id="999999999")
        source.refresh_from_db()

        SourceInputsStore.save(source, STORED_POSTGRES_INPUTS)

        rows = self._rows()
        assert len(rows) == 2
        assert _column(source) == str(max(row.id for row in rows))

    def test_two_writers_of_a_source_without_a_reference_make_one_row(self) -> None:
        source = self._raw_source(STORED_POSTGRES_INPUTS)
        first = ExternalDataSource.objects.get(pk=source.pk)
        second = ExternalDataSource.objects.get(pk=source.pk)

        SourceInputsStore.save(first, STORED_POSTGRES_INPUTS)
        SourceInputsStore.save(second, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        [row] = self._rows()
        assert row.sensitive_config == {"fields": {**POSTGRES_CONNECTION_FIELDS, "password": "fake-rotated"}}
        assert _column(source) == str(row.id)

    @parameterized.expand(
        [
            ("save", lambda source: SourceInputsStore.save(source, {})),
            (
                "assign_then_save_the_update_fields",
                lambda source: (
                    SourceInputsStore.assign(source, {}),
                    source.save(update_fields=[*INPUTS_UPDATE_FIELDS, "updated_at"]),
                ),
            ),
        ]
    )
    def test_a_write_without_credentials_drops_the_reference(
        self, _name: str, write: Callable[[ExternalDataSource], Any]
    ) -> None:
        source = self._raw_source({"schema": "public"}, column="123")

        write(source)

        assert _column(source) is None
        assert self._stored(source) == {}

    @parameterized.expand(
        [
            (
                "typed_in",
                ExternalDataSourceType.POSTGRES,
                STORED_POSTGRES_INPUTS,
                {**STORED_POSTGRES_SETTINGS_AND_RUNTIME, CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT},
                STORED_POSTGRES_INPUTS,
            ),
            (
                "oauth",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                {CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT},
                {"hubspot_integration_id": 7},
            ),
        ]
    )
    def test_an_update_of_an_unstripped_source_writes_the_stripped_form(
        self,
        _name: str,
        source_type: str,
        inputs: dict[str, Any],
        stripped: dict[str, Any],
        loaded: dict[str, Any],
    ) -> None:
        source = self._raw_source(inputs, source_type)

        with time_machine.travel(STRIPPED_AT, tick=False):
            SourceInputsStore.save(source, inputs)

        assert SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk)) == stripped
        for load in self._loads(source):
            assert load() == loaded

    def test_update_runtime_does_not_touch_the_integration_or_the_column(self) -> None:
        source = self._create()
        [row] = self._rows()
        # A sync holds an old copy of the source while another writer changes the column.
        ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id="123")

        SourceInputsStore.update_runtime(source, {"cdc_consistent_point": "0/16B3748"})

        [after] = self._rows()
        assert after.sensitive_config == row.sensitive_config
        assert _column(source) == "123"

    def test_update_oauth_inputs_keeps_the_stored_column(self) -> None:
        source = self._create({"hubspot_secret_key": "fake-old"}, source_type=ExternalDataSourceType.HUBSPOT)
        ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id="123")

        SourceInputsStore.update_oauth_inputs(source, {"hubspot_secret_key": "fake-new"})

        assert SourceInputsStore.load_stored(source) == {"hubspot_secret_key": "fake-new"}
        assert _column(source) == "123"

    def test_update_oauth_inputs_refuses_a_source_with_typed_in_credentials(self) -> None:
        source = _source(ExternalDataSourceType.POSTGRES, dict(STORED_POSTGRES_INPUTS))
        with self.assertRaises(ValueError):
            SourceInputsStore.update_oauth_inputs(source, {"password": "fake-new"})
        assert source.job_inputs == STORED_POSTGRES_INPUTS

    @parameterized.expand(
        [
            ("unstripped", STORED_POSTGRES_INPUTS),
            ("stripped", {**STORED_POSTGRES_SETTINGS_AND_RUNTIME, CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT}),
        ]
    )
    def test_read_takes_connection_fields_from_the_row_and_ignores_job_inputs(
        self, _name: str, inputs: dict[str, Any]
    ) -> None:
        reference = self._create()
        # The row also holds `schema`, a sync setting. Settings and runtime keys always come from job_inputs.
        _write_row(reference, {**POSTGRES_CONNECTION_FIELDS, "password": "fake-row-password", "schema": "fake-row"})
        source = self._raw_source(inputs, column=_column(reference))

        for load in self._loads(source):
            before = _read_count("integration")
            assert load() == {**STORED_POSTGRES_INPUTS, "password": "fake-row-password"}
            assert _read_count("integration") - before == 1

    @parameterized.expand(
        [
            ("typed_in_type_without_connection_fields", ExternalDataSourceType.POSTGRES, {"schema": "public"}),
            ("file_upload", ExternalDataSourceType.FILEUPLOAD, {"upload_id": "u1", "filename": "a.csv"}),
            ("custom", ExternalDataSourceType.CUSTOM, {"manifest": "{}"}),
            ("unknown_type", "NotARealSource", {"host": "x", "password": "fake"}),
        ]
    )
    def test_read_of_a_source_without_a_row_returns_job_inputs(
        self, _name: str, source_type: str, inputs: dict[str, Any]
    ) -> None:
        source = self._raw_source(inputs, source_type)

        for load in self._loads(source):
            before = _read_count("no_row", source_type)
            assert load() == inputs
            assert _read_count("no_row", source_type) - before == 1

    @parameterized.expand(
        [
            # (name, source type, job_inputs, column, expected inputs)
            (
                "column_matches_top_level",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                "7",
                {"hubspot_integration_id": 7},
            ),
            (
                "column_wins_over_job_inputs",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                "8",
                {"hubspot_integration_id": 8},
            ),
            ("column_alone_top_level", ExternalDataSourceType.HUBSPOT, {}, "7", {"hubspot_integration_id": 7}),
            (
                "column_alone_nested",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth"}, "stripe_account_id": "acct"},
                "7",
                {"auth_method": {"selection": "oauth", "stripe_integration_id": 7}, "stripe_account_id": "acct"},
            ),
            ("column_alone_hidden_slack_key", ExternalDataSourceType.SLACK, {}, "7", {"slack_integration_id": 7}),
            (
                "column_alone_pardot_next_to_typed_in_field",
                ExternalDataSourceType.PARDOT,
                {"environment": "sandbox", "business_unit_id": "b"},
                "7",
                {"environment": "sandbox", "business_unit_id": "b", "pardot_integration_id": 7},
            ),
        ]
    )
    def test_read_of_an_oauth_source_takes_the_pointer_from_the_column(
        self,
        _name: str,
        source_type: str,
        inputs: dict[str, Any],
        column: str | None,
        expected: dict[str, Any],
    ) -> None:
        source = self._raw_source(inputs, source_type, column=column)

        for load in self._loads(source):
            before = _read_count("oauth_reference", source_type)
            assert load() == expected
            assert _read_count("oauth_reference", source_type) - before == 1

    @parameterized.expand(
        [
            ("top_level_no_pointer", ExternalDataSourceType.HUBSPOT, {}, "no_row"),
            ("hidden_slack_key_no_pointer", ExternalDataSourceType.SLACK, {}, "no_row"),
            (
                "nested_no_pointer",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth"}, "stripe_account_id": "acct"},
                "no_row",
            ),
            (
                "top_level_pointer_in_inputs",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                "oauth_reference",
            ),
            (
                "nested_pointer_in_inputs",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}, "stripe_account_id": "acct"},
                "oauth_reference",
            ),
        ]
    )
    def test_read_of_an_unstripped_oauth_source_without_a_column_keeps_the_inputs(
        self, _name: str, source_type: str, inputs: dict[str, Any], expected_result: str
    ) -> None:
        source = self._raw_source(inputs, source_type, column=None)

        for load in self._loads(source):
            before = _read_count(expected_result, source_type)
            assert load() == inputs
            assert _read_count(expected_result, source_type) - before == 1

    def test_a_database_error_on_read_raises(self) -> None:
        source = self._create()
        with (
            patch.object(WarehouseSourceCredentialsStore, "get", side_effect=RuntimeError("store down")),
            patch.object(WarehouseSourceCredentialsStore, "get_many", side_effect=RuntimeError("store down")),
        ):
            before = _read_count("error")
            with self.assertRaises(RuntimeError):
                SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))
            assert SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)]) == {}
            assert _read_count("error") - before == 2

    def test_load_many_reads_the_integration_rows_in_one_query(self) -> None:
        sources = [self._create() for _ in range(3)]
        loaded_sources = list(ExternalDataSource.objects.filter(pk__in=[source.pk for source in sources]))
        SourceInputsStore.load(loaded_sources[0])

        before = _read_count("integration")
        with _assert_selects(1):
            loaded = SourceInputsStore.load_many(loaded_sources)

        assert _read_count("integration") - before == 3
        assert {inputs["password"] for inputs in loaded.values()} == {"fake-password"}
        assert set(loaded) == {source.id for source in sources}

    def test_preload_reads_the_integration_rows_once_for_later_loads(self) -> None:
        sources = [self._create() for _ in range(3)]
        loaded_sources = list(ExternalDataSource.objects.filter(pk__in=[source.pk for source in sources]))
        SourceInputsStore.load(loaded_sources[0])

        with _assert_selects(1):
            SourceInputsStore.preload(loaded_sources)
        before = _read_count("integration")
        with _assert_selects(0):
            for source in loaded_sources * 2:
                assert SourceInputsStore.load(source)["password"] == "fake-password"
        assert _read_count("integration") - before == 6

        SourceInputsStore.save(loaded_sources[0], {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})
        assert SourceInputsStore.load(loaded_sources[0])["password"] == "fake-rotated"

    def test_read_drops_a_row_key_that_is_now_a_setting(self) -> None:
        inputs = {key: value for key, value in STORED_POSTGRES_INPUTS.items() if key != "schema"}
        source = self._create(inputs)
        _write_row(source, {**POSTGRES_CONNECTION_FIELDS, "schema": "fake-row-schema"})

        assert self._stored(source) == inputs

    def test_failed_source_save_rolls_back_the_integration_row(self) -> None:
        source = self._create()
        with (
            patch.object(ExternalDataSource, "save", side_effect=RuntimeError("db down")),
            self.assertRaises(RuntimeError),
        ):
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._stored(source)["password"] == "fake-password"


class TestRequestedCredentialsReference(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk, source_id="s", connection_id="c", source_type=ExternalDataSourceType.POSTGRES
        )
        self.other = WarehouseSourceCredentialsStore.create(self.source, POSTGRES_CONNECTION_FIELDS)
        self.own = WarehouseSourceCredentialsStore.create(self.source, POSTGRES_CONNECTION_FIELDS)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_source = ExternalDataSource.objects.create(
            team_id=other_team.pk, source_id="s", connection_id="c", source_type=ExternalDataSourceType.POSTGRES
        )
        self.other_team_row = WarehouseSourceCredentialsStore.create(other_source, POSTGRES_CONNECTION_FIELDS)
        stripe = ExternalDataSource.objects.create(
            team_id=self.team.pk, source_id="s", connection_id="c", source_type=ExternalDataSourceType.STRIPE
        )
        self.other_kind_row = WarehouseSourceCredentialsStore.create(stripe, {"stripe_secret_key": "fake"})
        self.unmarked_row = IntegrationReference.from_legacy_id(
            IntegrationManager.postgresql.credentials.create(self.team.pk, external_id="unmarked", config={}).id
        )

    @parameterized.expand(
        [
            ("absent", lambda t: None, None),
            ("blank", lambda t: "", None),
            ("unchanged", lambda t: str(t.own), None),
            ("other_row_as_string", lambda t: str(t.other), "other"),
            ("other_row_as_number", lambda t: t.other.legacy_id, "other"),
        ]
    )
    def test_returns_the_reference_to_set(
        self, _name: str, requested: Callable[[Any], Any], expected_attr: str | None
    ) -> None:
        incoming = {} if requested(self) is None else {CREDENTIALS_REFERENCE_INPUT_KEY: requested(self)}

        result = rollout.requested_credentials_reference(self.source, incoming)

        assert result == (None if expected_attr is None else getattr(self, expected_attr))

    @parameterized.expand(
        [
            ("other_team", "other_team_row"),
            ("other_kind", "other_kind_row"),
            ("not_a_source_row", "unmarked_row"),
            ("missing", None),
            ("not_a_number", "not-a-number"),
            ("leading_zero", "007"),
        ]
    )
    def test_refuses_a_row_the_source_cannot_use(self, _name: str, attr: str | None) -> None:
        requested = 999999999 if attr is None else getattr(self, attr, attr)

        with self.assertRaises(UnusableCredentialsReferenceError):
            rollout.requested_credentials_reference(self.source, {CREDENTIALS_REFERENCE_INPUT_KEY: str(requested)})


def _column(source: ExternalDataSource) -> str | None:
    return ExternalDataSource.objects.get(pk=source.pk).credentials_integration_id


def _write_row(source: ExternalDataSource, fields: dict[str, Any]) -> None:
    WarehouseSourceCredentialsStore.update(ExternalDataSource.objects.get(pk=source.pk), fields)


@contextmanager
def _assert_selects(expected: int) -> Iterator[None]:
    # The credentials reads run in a savepoint, whose SAVEPOINT and RELEASE statements are not reads.
    with CaptureQueriesContext(connection) as captured:
        yield
    reads = [query["sql"] for query in captured.captured_queries if "SAVEPOINT" not in query["sql"]]
    assert len(reads) == expected, reads


def _read_count(result: str, source_type: str = ExternalDataSourceType.POSTGRES) -> float:
    return _sample(
        "posthog_warehouse_source_credentials_read_total",
        {"result": result, "source_type": str(source_type)},
    )


def _set_column(source: ExternalDataSource, ref: str) -> None:
    ExternalDataSource.objects.filter(pk=source.pk).update(credentials_integration_id=ref)


def _set_inputs(source: ExternalDataSource, changes: dict[str, Any]) -> None:
    fresh = ExternalDataSource.objects.get(pk=source.pk)
    inputs = SourceInputsStore.load(fresh)
    ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs={**inputs, **changes})


class TestSourceInputsStoreStripped(BaseTest):
    def _create(
        self, inputs: dict[str, Any] | None = None, source_type: str = ExternalDataSourceType.POSTGRES
    ) -> ExternalDataSource:
        with time_machine.travel(STRIPPED_AT, tick=False):
            return SourceInputsStore.create(
                inputs=STORED_POSTGRES_INPUTS if inputs is None else inputs,
                team_id=self.team.pk,
                source_id="source",
                connection_id="connection",
                status="Running",
                source_type=source_type,
            )

    def _stripped_source(
        self, inputs: dict[str, Any] | None = None, source_type: str = ExternalDataSourceType.POSTGRES
    ) -> ExternalDataSource:
        source = self._create(inputs, source_type)
        return ExternalDataSource.objects.get(pk=source.pk)

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk))

    def _row(self, source: ExternalDataSource) -> dict[str, Any] | None:
        return WarehouseSourceCredentialsStore.get(ExternalDataSource.objects.get(pk=source.pk))

    def _loads(self, source: ExternalDataSource) -> list[Callable[[], dict[str, Any]]]:
        return [
            lambda: SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)),
            lambda: SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)])[source.id],
        ]

    def test_stripped_source_loads_connection_fields_from_the_integration(self) -> None:
        source = self._stripped_source()
        assert self._stored(source) == {
            **STORED_POSTGRES_SETTINGS_AND_RUNTIME,
            CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT,
        }
        assert _column(source) is not None

        for load in self._loads(source):
            assert load() == STORED_POSTGRES_INPUTS
        assert SourceInputsStore.load_settings(ExternalDataSource.objects.get(pk=source.pk)) == (
            STORED_POSTGRES_SETTINGS_AND_RUNTIME
        )

    @parameterized.expand(
        [
            # (name, source type, inputs, stripped inputs, loaded inputs)
            (
                "top_level",
                ExternalDataSourceType.HUBSPOT,
                {"hubspot_integration_id": "7"},
                {},
                {"hubspot_integration_id": 7},
            ),
            (
                "nested_with_a_stale_pointer_under_the_other_option",
                ExternalDataSourceType.GITHUB,
                {
                    "auth_method": {"selection": "oauth", "github_integration_id": "7"},
                    "repository": "posthog/posthog",
                },
                {"auth_method": {"selection": "oauth"}, "repository": "posthog/posthog"},
                {"auth_method": {"selection": "oauth", "github_integration_id": 7}, "repository": "posthog/posthog"},
            ),
            (
                "slack_hidden_key",
                ExternalDataSourceType.SLACK,
                {"slack_integration_id": "7"},
                {},
                {"slack_integration_id": 7},
            ),
            (
                "pardot_keeps_its_typed_in_field",
                ExternalDataSourceType.PARDOT,
                {"pardot_integration_id": "7", "environment": "sandbox", "business_unit_id": "b"},
                {"environment": "sandbox", "business_unit_id": "b"},
                {"pardot_integration_id": 7, "environment": "sandbox", "business_unit_id": "b"},
            ),
        ]
    )
    def test_stripped_oauth_source_loads_its_pointer_from_the_column(
        self,
        _name: str,
        source_type: str,
        inputs: dict[str, Any],
        stripped: dict[str, Any],
        loaded: dict[str, Any],
    ) -> None:
        source = self._stripped_source(inputs, source_type)
        assert _column(source) == "7"
        assert self._stored(source) == {**stripped, CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT}

        for load in self._loads(source):
            assert load() == loaded

    def test_stripped_oauth_source_drops_a_stale_pointer_under_the_other_option(self) -> None:
        stale = {"auth_method": {"selection": "pat", "personal_access_token": "fake", "github_integration_id": "7"}}
        source = self._create({**stale, "repository": "posthog/posthog"}, ExternalDataSourceType.GITHUB)

        assert self._stored(source) == {"repository": "posthog/posthog", CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT}

    def test_stripped_slack_token_source_stays_typed_in(self) -> None:
        # Without its pasted token, Slack would read as a legacy OAuth source and use the column as its pointer.
        inputs = {"slack_access_token": "xoxb-fake"}
        source = self._stripped_source(inputs, ExternalDataSourceType.SLACK)
        row_reference = _column(source)
        assert row_reference is not None

        assert self._stored(source) == {
            CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY: "true",
            CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT,
        }
        assert rollout.in_use_oauth_slot(ExternalDataSourceType.SLACK, self._stored(source)) is None
        for load in self._loads(source):
            assert load() == inputs

        stored = ExternalDataSource.objects.get(pk=source.pk)
        SourceInputsStore.save(stored, {**inputs, "slack_access_token": "xoxb-rotated"})
        assert _column(source) == row_reference
        assert self._stored(source)[CONNECTION_FIELDS_STRIPPED_TYPED_IN_KEY] == "true"
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))["slack_access_token"] == (
            "xoxb-rotated"
        )

    @parameterized.expand(
        [
            (
                "missing_row",
                lambda source: Integration.objects._with_auth(ANY).filter(id=int(_column(source) or 0)).delete(),
                "missing",
            ),
            (
                "unreadable_row",
                lambda source: (
                    Integration.objects._with_auth(ANY).filter(id=int(_column(source) or 0)).update(sensitive_config={})
                ),
                "unreadable",
            ),
            # A source not yet stripped keeps its connection fields in job_inputs, but they are never a fallback.
            (
                "unstripped_without_a_column",
                lambda source: ExternalDataSource.objects.filter(pk=source.pk).update(
                    job_inputs=STORED_POSTGRES_INPUTS, credentials_integration_id=None
                ),
                "missing",
            ),
        ]
    )
    def test_source_without_a_readable_row_raises_and_never_falls_back(
        self, _name: str, change: Callable[[ExternalDataSource], Any], expected_result: str
    ) -> None:
        source = self._stripped_source()
        change(source)
        before = _read_count(expected_result)

        with self.assertRaises(SourceCredentialsMissingError):
            SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))
        assert SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)]) == {}

        assert _read_count(expected_result) - before == 2

    @parameterized.expand(
        [
            ("cleared", {}, None),
            ("uuid", {}, "0b7e8c3a-5f4d-4e2a-9c1b-2d3e4f5a6b7c"),
        ]
    )
    def test_oauth_source_without_a_legacy_id_in_the_column_raises(
        self, _name: str, job_inputs: dict[str, Any], column: str | None
    ) -> None:
        source = self._stripped_source({"hubspot_integration_id": "7"}, ExternalDataSourceType.HUBSPOT)
        ExternalDataSource.objects.filter(pk=source.pk).update(
            credentials_integration_id=column, **({"job_inputs": job_inputs} if job_inputs else {})
        )

        with self.assertRaises(SourceCredentialsMissingError):
            SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))
        assert SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)]) == {}

    @parameterized.expand(
        [
            ("save", lambda source, inputs: SourceInputsStore.save(source, inputs)),
            (
                "assign_then_model_save",
                lambda source, inputs: (SourceInputsStore.assign(source, inputs), source.save()),
            ),
        ]
    )
    def test_writes_to_a_stripped_source_put_connection_fields_only_in_the_integration(
        self, _name: str, write: Callable[[ExternalDataSource, dict[str, Any]], Any]
    ) -> None:
        source = self._stripped_source()
        reference = _column(source)

        inputs = SourceInputsStore.load(source)
        write(source, {**inputs, "password": "fake-rotated", "schema": "analytics"})
        SourceInputsStore.update_runtime(source, {"cdc_slot_name": "fake-new-slot"})

        assert self._stored(source) == {
            **STORED_POSTGRES_SETTINGS_AND_RUNTIME,
            "schema": "analytics",
            "cdc_slot_name": "fake-new-slot",
            CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT,
        }
        assert _column(source) == reference
        assert self._row(source) == {**POSTGRES_CONNECTION_FIELDS, "password": "fake-rotated"}

    def test_a_write_to_a_stripped_oauth_source_moves_the_new_pointer_to_the_column(self) -> None:
        source = self._stripped_source(
            {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}, "stripe_account_id": "acct"},
            ExternalDataSourceType.STRIPE,
        )

        inputs = SourceInputsStore.load(source)
        SourceInputsStore.save(source, {**inputs, "auth_method": {"selection": "oauth", "stripe_integration_id": 8}})

        assert _column(source) == "8"
        assert self._stored(source) == {
            "auth_method": {"selection": "oauth"},
            "stripe_account_id": "acct",
            CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT,
        }

    def test_a_failed_integration_write_fails_the_save_of_a_stripped_source(self) -> None:
        source = self._stripped_source()
        stored = self._stored(source)

        with (
            patch.object(WarehouseSourceCredentialsStore, "update", side_effect=RuntimeError("store down")),
            self.assertRaises(RuntimeError),
        ):
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._stored(source) == stored

    def test_a_shared_row_of_a_stripped_source_is_never_skipped(self) -> None:
        source = self._stripped_source()
        ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id="other",
            connection_id="other",
            status="Running",
            source_type=ExternalDataSourceType.POSTGRES,
            job_inputs=STORED_POSTGRES_INPUTS,
            credentials_integration_id=_column(source),
        )

        with self.assertRaises(SharedCredentialsError):
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._row(source) == POSTGRES_CONNECTION_FIELDS

    @parameterized.expand(
        [
            ("typed_in", ExternalDataSourceType.POSTGRES, STORED_POSTGRES_INPUTS, True),
            ("oauth_with_a_pointer", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": "7"}, True),
            ("oauth_without_a_pointer", ExternalDataSourceType.HUBSPOT, {}, False),
        ]
    )
    def test_create_strips_a_source_with_credentials(
        self, _name: str, source_type: str, inputs: dict[str, Any], expect_stripped: bool
    ) -> None:
        source = self._create(inputs, source_type=source_type)

        assert SourceInputsStore.is_stripped(ExternalDataSource.objects.get(pk=source.pk)) is expect_stripped
        assert (self._stored(source) == inputs) is not expect_stripped
