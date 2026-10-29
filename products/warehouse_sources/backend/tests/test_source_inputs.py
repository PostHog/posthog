import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models import Team
from posthog.models.integration import ANY, Integration

from products.integrations.backend.facade.api import IntegrationManager
from products.warehouse_sources.backend.facade.contracts import (
    CONNECTION_FIELDS_STRIPPED_KEY,
    CREDENTIALS_REFERENCE_KEY,
    SharedCredentialsEdit,
    SharedCredentialsError,
    SourceCredentialsMissingError,
    UnusableCredentialsReferenceError,
)
from products.warehouse_sources.backend.logic import source_credentials_rollout as rollout
from products.warehouse_sources.backend.logic.source_credentials import WarehouseSourceCredentialsStore
from products.warehouse_sources.backend.logic.source_credentials_rollout import (
    DUAL_WRITE_FLAG,
    READ_FLAG,
    STRIP_FLAG,
    reset_caches,
)
from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore, UnreadableSourceInputsError
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports import schema_flags
from products.warehouse_sources.backend.types import ExternalDataSourceType

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
            ("mapping", {"host": "h", "schema": "s"}, {"host": "h", "schema": "s"}),
            ("json_string", json.dumps({"host": "h"}), {"host": "h"}),
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
        source = _source(job_inputs={"host": "h"})
        SourceInputsStore.load(source)["host"] = "changed"
        assert SourceInputsStore.load(source) == {"host": "h"}

    def test_load_many_skips_unreadable_sources(self) -> None:
        good = _source(job_inputs={"host": "h"})
        bad = _source(job_inputs=["not", "a", "mapping"])
        assert SourceInputsStore.load_many([good, bad]) == {good.id: {"host": "h"}}

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

        result = SourceInputsStore.update_runtime(
            source, {"cdc_consistent_point": "0/16B3748"}, remove=["cdc_slot_name", "cdc_absent_key"]
        )

        expected = {**STORED_POSTGRES_INPUTS, "cdc_consistent_point": "0/16B3748"}
        del expected["cdc_slot_name"]
        assert result == expected
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == expected

    def test_save_rewrites_a_string_value_as_a_mapping(self) -> None:
        source = self._create({})
        ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs=json.dumps({"host": "h"}))
        source.refresh_from_db()
        assert SourceInputsStore.stored_as_string(source)

        SourceInputsStore.save(source, SourceInputsStore.load(source))

        source.refresh_from_db()
        assert not SourceInputsStore.stored_as_string(source)
        assert SourceInputsStore.load(source) == {"host": "h"}


POSTGRES_CONNECTION_FIELDS: dict[str, str] = {
    key: STORED_POSTGRES_INPUTS[key] for key in ("host", "port", "database", "user", "password")
}


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


DUAL_WRITE_TOTAL = "posthog_warehouse_source_credentials_dual_write_total"
REF = CREDENTIALS_REFERENCE_KEY


def _compare_count(result: str) -> float:
    return _sample(
        "posthog_warehouse_source_credentials_shadow_compare_total",
        {"result": result, "source_type": ExternalDataSourceType.POSTGRES.value},
    )


class TestSourceInputsStoreCredentialsMirror(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_caches()
        self.addCleanup(reset_caches)

    def _flag(self, **kwargs: Any) -> Any:
        return patch.object(schema_flags.posthoganalytics, "feature_enabled", **kwargs)

    def _flags(self, *enabled: str) -> Any:
        return self._flag(side_effect=lambda flag, *args, **kwargs: flag in enabled)

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

    def _rows(self) -> list[Any]:
        return IntegrationManager.source("postgresql").credentials.list(self.team.pk)

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))

    def _shared_sources(self) -> list[ExternalDataSource]:
        first = self._create()
        return [first, self._create({**STORED_POSTGRES_INPUTS, CREDENTIALS_REFERENCE_KEY: self._stored(first)[REF]})]

    @parameterized.expand(
        [
            ("flag_off", {"return_value": False}),
            ("flag_error", {"side_effect": RuntimeError("flags down")}),
        ]
    )
    def test_writes_nothing_to_the_integration_when_the_flag_is_not_on(
        self, _name: str, flag_kwargs: dict[str, Any]
    ) -> None:
        with self._flag(**flag_kwargs):
            source = self._create()
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._rows() == []
        assert self._stored(source) == {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"}

    def test_a_flag_error_is_not_cached(self) -> None:
        with self._flag(side_effect=RuntimeError("flags down")):
            source = self._create()
        assert self._rows() == []

        with self._flags(DUAL_WRITE_FLAG):
            SourceInputsStore.save(source, STORED_POSTGRES_INPUTS)

        [row] = self._rows()
        assert row.sensitive_config == {"fields": POSTGRES_CONNECTION_FIELDS}

    def test_create_makes_a_row_and_later_saves_update_it(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
            [row] = self._rows()
            assert self._stored(source) == {**STORED_POSTGRES_INPUTS, REF: str(row.id)}
            assert row.config["warehouse_source_type"] == "Postgres"
            assert row.sensitive_config == {"fields": POSTGRES_CONNECTION_FIELDS}

            # A writer that builds the inputs from a parsed config sends no reference.
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        [updated] = self._rows()
        assert updated.id == row.id
        assert updated.sensitive_config == {"fields": {**POSTGRES_CONNECTION_FIELDS, "password": "fake-rotated"}}
        assert self._stored(source) == {**STORED_POSTGRES_INPUTS, "password": "fake-rotated", REF: str(row.id)}

    def test_a_failed_insert_leaves_no_row(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
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
            ("oauth_only", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": "7"}),
            ("custom_has_no_kind", ExternalDataSourceType.CUSTOM, {"manifest": "{}"}),
            ("stripe_oauth_option", ExternalDataSourceType.STRIPE, None),
        ]
    )
    def test_a_source_without_typed_in_credentials_gets_no_row(
        self, _name: str, source_type: str, inputs: dict[str, Any] | None
    ) -> None:
        if inputs is None:
            inputs = {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}}
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create(inputs, source_type=source_type)

        assert IntegrationManager.any.with_source_rows().list(self.team.pk) == []
        assert REF not in SourceInputsStore.load(source)

    @parameterized.expand(
        [
            ("skip", SharedCredentialsEdit.SKIP, "fake-password", "shared_skip"),
            ("confirmed", SharedCredentialsEdit.CONFIRMED, "fake-rotated", "success"),
        ]
    )
    def test_edit_of_a_shared_row(
        self, _name: str, edit: SharedCredentialsEdit, row_password: str, outcome: str
    ) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            first, _second = self._shared_sources()
            before = _sample(DUAL_WRITE_TOTAL, {"outcome": outcome})

            first.refresh_from_db()
            SourceInputsStore.assign(
                first, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"}, shared_credentials=edit
            )
            first.save()

            [row] = self._rows()
        assert row.sensitive_config["fields"]["password"] == row_password
        assert self._stored(first)["password"] == "fake-rotated"
        assert _sample(DUAL_WRITE_TOTAL, {"outcome": outcome}) - before == 1

    def test_refused_edit_of_a_shared_row_raises_and_unchanged_fields_do_not(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
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

    def test_a_host_change_on_a_shared_row_makes_a_new_row(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            first, second = self._shared_sources()
            shared_id = self._stored(first)[REF]
            first.refresh_from_db()

            SourceInputsStore.save(first, {**STORED_POSTGRES_INPUTS, "host": "other.example.com"})

        assert self._stored(second)[REF] == shared_id
        assert self._stored(first)[REF] != shared_id
        assert len(self._rows()) == 2

    def test_a_dangling_reference_gets_a_new_row(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create({**STORED_POSTGRES_INPUTS, REF: "999999999"})

        [row] = self._rows()
        assert self._stored(source)[REF] == str(row.id)
        assert row.sensitive_config == {"fields": POSTGRES_CONNECTION_FIELDS}

    def test_upsert_failure_does_not_block_the_job_inputs_save_while_reads_use_job_inputs(self) -> None:
        before = _sample(DUAL_WRITE_TOTAL, {"outcome": "upsert_error"})
        with (
            self._flags(DUAL_WRITE_FLAG),
            patch.object(WarehouseSourceCredentialsStore, "create", side_effect=RuntimeError("store down")),
        ):
            source = self._create()
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._stored(source) == {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"}
        assert _sample(DUAL_WRITE_TOTAL, {"outcome": "upsert_error"}) - before == 2

    def test_upsert_failure_fails_the_save_while_reads_use_the_integration(self) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            source = self._create()
            with (
                patch.object(WarehouseSourceCredentialsStore, "update", side_effect=RuntimeError("store down")),
                self.assertRaises(RuntimeError),
            ):
                SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

            assert self._stored(source)["password"] == "fake-password"
        source.refresh_from_db()
        assert source.job_inputs["password"] == "fake-password"

    def test_update_runtime_does_not_touch_the_integration(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
            [row] = self._rows()

            SourceInputsStore.update_runtime(source, {"cdc_consistent_point": "0/16B3748"})

        [after] = self._rows()
        assert after.sensitive_config == row.sensitive_config
        assert self._stored(source)[REF] == str(row.id)

    @parameterized.expand(
        [
            ("match", lambda source: None, "match"),
            ("missing_row", lambda source: _set_reference(source, "999999999"), "missing_row"),
            (
                "unreadable",
                lambda source: (
                    Integration.objects._with_auth(ANY).filter(id=_reference(source)).update(sensitive_config={})
                ),
                "unreadable",
            ),
            (
                "field_mismatch",
                lambda source: WarehouseSourceCredentialsStore.update(
                    source, _reference(source), {**POSTGRES_CONNECTION_FIELDS, "password": "fake-other"}
                ),
                "field_mismatch",
            ),
        ]
    )
    def test_shadow_compare_counts_the_result_and_keeps_the_returned_value(
        self, _name: str, change: Callable[[ExternalDataSource], Any], expected_result: str
    ) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
            change(source)
            expected = SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))

            for load in (
                lambda: SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)),
                lambda: SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)])[source.id],
            ):
                reset_caches()
                before = _compare_count(expected_result)
                assert load() == expected
                assert _compare_count(expected_result) - before == 1

    def test_shadow_compare_runs_once_per_interval_for_a_source(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
            before = _compare_count("match")

            for _ in range(3):
                SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))

        assert _compare_count("match") - before == 1

    def test_shadow_compare_never_raises(self) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
        expected = self._stored(source)
        with (
            self._flags(DUAL_WRITE_FLAG),
            patch.object(WarehouseSourceCredentialsStore, "get", side_effect=RuntimeError("store down")),
            patch.object(WarehouseSourceCredentialsStore, "get_many", side_effect=RuntimeError("store down")),
        ):
            reset_caches()
            assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == expected
            reset_caches()
            assert SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)]) == {source.id: expected}

    def _loads(self, source: ExternalDataSource) -> list[Callable[[], dict[str, Any]]]:
        return [
            lambda: SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)),
            lambda: SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)])[source.id],
        ]

    @parameterized.expand(
        [
            ("both_flags_on", (DUAL_WRITE_FLAG, READ_FLAG), "integration", "fake-row-password"),
            ("read_flag_off", (DUAL_WRITE_FLAG,), None, "fake-password"),
            ("dual_write_flag_off", (READ_FLAG,), "fallback_dual_write_off", "fake-password"),
            ("no_flags", (), None, "fake-password"),
        ]
    )
    def test_read_flag_takes_connection_fields_from_the_integration(
        self, _name: str, flags: tuple[str, ...], expected_result: str | None, expected_password: str
    ) -> None:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
        # The row also holds `schema`, a sync setting. Settings and runtime keys always come from job_inputs.
        _write_row(source, {**POSTGRES_CONNECTION_FIELDS, "password": "fake-row-password", "schema": "fake-row-schema"})
        expected = {**STORED_POSTGRES_INPUTS, "password": expected_password, REF: _reference(source)}

        with self._flags(*flags):
            for load in self._loads(source):
                reset_caches()
                before = _read_count(expected_result) if expected_result else 0.0
                assert load() == expected
                if expected_result:
                    assert _read_count(expected_result) - before == 1

    @parameterized.expand(
        [
            (
                "missing_row",
                STORED_POSTGRES_INPUTS,
                lambda source: _set_reference(source, "999999999"),
                "fallback_missing",
            ),
            (
                "unreadable_row",
                STORED_POSTGRES_INPUTS,
                lambda source: (
                    Integration.objects._with_auth(ANY).filter(id=_reference(source)).update(sensitive_config={})
                ),
                "fallback_unreadable",
            ),
            ("empty_row", STORED_POSTGRES_INPUTS, lambda source: _write_row(source, {}), "fallback_empty"),
            ("no_connection_fields_in_job_inputs", {"schema": "public"}, lambda source: None, "no_row"),
        ]
    )
    def test_read_falls_back_to_job_inputs_and_counts_why(
        self,
        _name: str,
        inputs: dict[str, str],
        change: Callable[[ExternalDataSource], Any],
        expected_result: str,
    ) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            source = self._create(inputs)
            change(source)
            expected = dict(ExternalDataSource.objects.get(pk=source.pk).job_inputs)

            for load in self._loads(source):
                reset_caches()
                before = _read_count(expected_result)
                assert load() == expected
                assert _read_count(expected_result) - before == 1

    @parameterized.expand(
        [
            ("oauth_only", ExternalDataSourceType.HUBSPOT, {"hubspot_integration_id": "7", "schema": "public"}),
            (
                "stripe_oauth_option",
                ExternalDataSourceType.STRIPE,
                {"auth_method": {"selection": "oauth", "stripe_integration_id": "7"}, "stripe_account_id": "acct"},
            ),
        ]
    )
    def test_read_of_an_oauth_connection_keeps_job_inputs(
        self, _name: str, source_type: str, inputs: dict[str, Any]
    ) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            source = self._create(inputs, source_type=source_type)

            for load in self._loads(source):
                reset_caches()
                assert load() == inputs

    def test_read_falls_back_to_job_inputs_when_the_credentials_store_fails(self) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            source = self._create()
            expected = {**STORED_POSTGRES_INPUTS, REF: _reference(source)}
            with (
                patch.object(WarehouseSourceCredentialsStore, "get", side_effect=RuntimeError("store down")),
                patch.object(WarehouseSourceCredentialsStore, "get_many", side_effect=RuntimeError("store down")),
            ):
                for load in self._loads(source):
                    reset_caches()
                    before = _read_count("fallback_error")
                    assert load() == expected
                    assert _read_count("fallback_error") - before == 1

    def test_load_many_reads_the_integration_rows_in_one_query(self) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            sources = [self._create() for _ in range(3)]
            for source in sources:
                _write_row(source, {**POSTGRES_CONNECTION_FIELDS, "password": "fake-row"})
            loaded_sources = list(ExternalDataSource.objects.filter(pk__in=[source.pk for source in sources]))
            SourceInputsStore.load(loaded_sources[0])

            with _assert_selects(1):
                loaded = SourceInputsStore.load_many(loaded_sources)

        assert {inputs["password"] for inputs in loaded.values()} == {"fake-row"}
        assert set(loaded) == {source.id for source in sources}

    def test_preload_reads_the_integration_rows_once_for_later_loads(self) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            sources = [self._create() for _ in range(3)]
            for source in sources:
                _write_row(source, {**POSTGRES_CONNECTION_FIELDS, "password": "fake-row"})
            loaded_sources = list(ExternalDataSource.objects.filter(pk__in=[source.pk for source in sources]))
            SourceInputsStore.load(loaded_sources[0])

            with _assert_selects(1):
                SourceInputsStore.preload(loaded_sources)
            with _assert_selects(0):
                for source in loaded_sources * 2:
                    assert SourceInputsStore.load(source)["password"] == "fake-row"

            SourceInputsStore.save(loaded_sources[0], {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})
            assert SourceInputsStore.load(loaded_sources[0])["password"] == "fake-rotated"

    def test_read_drops_a_row_key_that_is_now_a_setting(self) -> None:
        inputs = {key: value for key, value in STORED_POSTGRES_INPUTS.items() if key != "schema"}
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            source = self._create(inputs)
            _write_row(source, {**POSTGRES_CONNECTION_FIELDS, "schema": "fake-row-schema"})

            assert self._stored(source) == {**inputs, REF: _reference(source)}

    def test_failed_source_save_rolls_back_the_integration_row(self) -> None:
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
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
        self.own = WarehouseSourceCredentialsStore.create(self.source, POSTGRES_CONNECTION_FIELDS)
        self.other = WarehouseSourceCredentialsStore.create(self.source, POSTGRES_CONNECTION_FIELDS)
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_source = ExternalDataSource.objects.create(
            team_id=other_team.pk, source_id="s", connection_id="c", source_type=ExternalDataSourceType.POSTGRES
        )
        self.other_team_row = WarehouseSourceCredentialsStore.create(other_source, POSTGRES_CONNECTION_FIELDS)
        stripe = ExternalDataSource.objects.create(
            team_id=self.team.pk, source_id="s", connection_id="c", source_type=ExternalDataSourceType.STRIPE
        )
        self.other_kind_row = WarehouseSourceCredentialsStore.create(stripe, {"stripe_secret_key": "fake"})
        self.unmarked_row = IntegrationManager.postgresql.credentials.create(
            self.team.pk, external_id="unmarked", config={}
        ).id

    @parameterized.expand(
        [
            ("absent", lambda t: None, None),
            ("blank", lambda t: "", None),
            ("unchanged", lambda t: str(t.own), None),
            ("other_row_of_the_kind", lambda t: t.other, "other"),
        ]
    )
    def test_returns_the_reference_to_set(
        self, _name: str, requested: Callable[[Any], Any], expected_attr: str | None
    ) -> None:
        incoming = {} if requested(self) is None else {REF: requested(self)}

        result = rollout.requested_credentials_reference(self.source, {REF: str(self.own)}, incoming)

        assert result == (None if expected_attr is None else getattr(self, expected_attr))

    @parameterized.expand(
        [
            ("other_team", "other_team_row"),
            ("other_kind", "other_kind_row"),
            ("not_a_source_row", "unmarked_row"),
            ("missing", None),
            ("not_a_number", "not-a-number"),
        ]
    )
    def test_refuses_a_row_the_source_cannot_use(self, _name: str, attr: str | None) -> None:
        requested = 999999999 if attr is None else getattr(self, attr, attr)

        with self.assertRaises(UnusableCredentialsReferenceError):
            rollout.requested_credentials_reference(self.source, {REF: str(self.own)}, {REF: requested})


def _reference(source: ExternalDataSource) -> str:
    return SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))[REF]


def _write_row(source: ExternalDataSource, fields: dict[str, Any]) -> None:
    WarehouseSourceCredentialsStore.update(source, _reference(source), fields)


@contextmanager
def _assert_selects(expected: int) -> Iterator[None]:
    # The credentials reads run in a savepoint, whose SAVEPOINT and RELEASE statements are not reads.
    with CaptureQueriesContext(connection) as captured:
        yield
    reads = [query["sql"] for query in captured.captured_queries if "SAVEPOINT" not in query["sql"]]
    assert len(reads) == expected, reads


def _read_count(result: str) -> float:
    return _sample(
        "posthog_warehouse_source_credentials_read_total",
        {"result": result, "source_type": ExternalDataSourceType.POSTGRES.value},
    )


def _set_reference(source: ExternalDataSource, ref: str) -> None:
    fresh = ExternalDataSource.objects.get(pk=source.pk)
    inputs = SourceInputsStore.load(fresh)
    ExternalDataSource.objects.filter(pk=source.pk).update(job_inputs={**inputs, REF: ref})


STORED_POSTGRES_SETTINGS_AND_RUNTIME: dict[str, str] = {
    key: value for key, value in STORED_POSTGRES_INPUTS.items() if key not in POSTGRES_CONNECTION_FIELDS
}
STRIPPED_AT = "2026-01-01T00:00:00+00:00"


class TestSourceInputsStoreStripped(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        reset_caches()
        self.addCleanup(reset_caches)

    def _flags(self, *enabled: str) -> Any:
        return patch.object(
            schema_flags.posthoganalytics, "feature_enabled", side_effect=lambda flag, *args, **kwargs: flag in enabled
        )

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

    def _stripped_source(self) -> ExternalDataSource:
        with self._flags(DUAL_WRITE_FLAG):
            source = self._create()
        SourceInputsStore.write_stripped(source, stripped_at=STRIPPED_AT)
        reset_caches()
        return ExternalDataSource.objects.get(pk=source.pk)

    def _stored(self, source: ExternalDataSource) -> dict[str, Any]:
        return SourceInputsStore.load_stored(ExternalDataSource.objects.get(pk=source.pk))

    def _row(self, source: ExternalDataSource) -> dict[str, Any] | None:
        return WarehouseSourceCredentialsStore.get(source, self._stored(source).get(REF))

    def _loads(self, source: ExternalDataSource) -> list[Callable[[], dict[str, Any]]]:
        return [
            lambda: SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)),
            lambda: SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)])[source.id],
        ]

    @parameterized.expand(
        [("no_flags", ()), ("dual_write_only", (DUAL_WRITE_FLAG,)), ("all_flags", (DUAL_WRITE_FLAG, READ_FLAG))]
    )
    def test_stripped_source_loads_connection_fields_from_the_integration_whatever_the_flags(
        self, _name: str, flags: tuple[str, ...]
    ) -> None:
        source = self._stripped_source()
        reference = self._stored(source)[REF]
        # The strip keeps the reference, so the source still finds its row.
        assert self._stored(source) == {
            **STORED_POSTGRES_SETTINGS_AND_RUNTIME,
            REF: reference,
            CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT,
        }

        with self._flags(*flags):
            for load in self._loads(source):
                assert load() == {**STORED_POSTGRES_INPUTS, REF: reference}
            assert SourceInputsStore.load_settings(ExternalDataSource.objects.get(pk=source.pk)) == (
                STORED_POSTGRES_SETTINGS_AND_RUNTIME
            )

    @parameterized.expand(
        [
            (
                "missing_row",
                lambda ref: Integration.objects._with_auth(ANY).filter(id=ref).delete(),
                "stripped_missing",
            ),
            (
                "unreadable_row",
                lambda ref: Integration.objects._with_auth(ANY).filter(id=ref).update(sensitive_config={}),
                "stripped_unreadable",
            ),
        ]
    )
    def test_stripped_source_without_a_readable_row_raises_and_never_falls_back(
        self, _name: str, change_row: Callable[[Any], Any], expected_result: str
    ) -> None:
        source = self._stripped_source()
        change_row(self._stored(source)[REF])
        before = _read_count(expected_result)

        with self._flags(DUAL_WRITE_FLAG, READ_FLAG):
            with self.assertRaises(SourceCredentialsMissingError):
                SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))
            assert SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)]) == {}

        assert _read_count(expected_result) - before == 2

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
        reference = self._stored(source)[REF]

        with self._flags():
            inputs = SourceInputsStore.load(source)
            write(source, {**inputs, "password": "fake-rotated", "schema": "analytics"})
            SourceInputsStore.update_runtime(source, {"cdc_slot_name": "fake-new-slot"})

        assert self._stored(source) == {
            **STORED_POSTGRES_SETTINGS_AND_RUNTIME,
            "schema": "analytics",
            "cdc_slot_name": "fake-new-slot",
            REF: reference,
            CONNECTION_FIELDS_STRIPPED_KEY: STRIPPED_AT,
        }
        assert self._row(source) == {**POSTGRES_CONNECTION_FIELDS, "password": "fake-rotated"}

    def test_a_failed_integration_write_fails_the_save_of_a_stripped_source(self) -> None:
        source = self._stripped_source()
        stored = self._stored(source)

        with (
            self._flags(),
            patch.object(WarehouseSourceCredentialsStore, "update", side_effect=RuntimeError("store down")),
            self.assertRaises(RuntimeError),
        ):
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._stored(source) == stored

    def test_a_shared_row_of_a_stripped_source_is_never_skipped(self) -> None:
        source = self._stripped_source()
        with self._flags(DUAL_WRITE_FLAG):
            self._create({**STORED_POSTGRES_INPUTS, REF: self._stored(source)[REF]})

        with self._flags(), self.assertRaises(SharedCredentialsError):
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert self._row(source) == POSTGRES_CONNECTION_FIELDS

    @parameterized.expand(
        [
            ("strip_flag_on", (DUAL_WRITE_FLAG, READ_FLAG, STRIP_FLAG), True),
            ("strip_flag_without_read_flag", (DUAL_WRITE_FLAG, STRIP_FLAG), False),
            ("read_flags_only", (DUAL_WRITE_FLAG, READ_FLAG), False),
        ]
    )
    def test_create_strips_a_new_source_only_with_the_strip_and_read_flags(
        self, _name: str, flags: tuple[str, ...], expect_stripped: bool
    ) -> None:
        with self._flags(*flags):
            source = self._create()
            reference = self._stored(source)[REF]
            assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == {
                **STORED_POSTGRES_INPUTS,
                REF: reference,
            }

        stored = self._stored(source)
        assert SourceInputsStore.is_stripped(ExternalDataSource.objects.get(pk=source.pk)) is expect_stripped
        assert ("password" in stored) is not expect_stripped
        assert self._row(source) == POSTGRES_CONNECTION_FIELDS

    def test_create_never_strips_an_oauth_connection(self) -> None:
        inputs = {"hubspot_integration_id": "7", "schema": "public"}
        with self._flags(DUAL_WRITE_FLAG, READ_FLAG, STRIP_FLAG):
            source = self._create(inputs, source_type=ExternalDataSourceType.HUBSPOT)

            assert not SourceInputsStore.is_stripped(ExternalDataSource.objects.get(pk=source.pk))
            assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == inputs
