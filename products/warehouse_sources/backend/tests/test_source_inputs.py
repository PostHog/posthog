import json
from collections.abc import Callable
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.integration import Integration

from products.warehouse_sources.backend.logic.source_credentials import WarehouseSourceCredentialsStore
from products.warehouse_sources.backend.logic.source_credentials_rollout import reset_caches
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

    def _create(self, inputs: dict[str, Any] | None = None) -> ExternalDataSource:
        return SourceInputsStore.create(
            inputs=STORED_POSTGRES_INPUTS if inputs is None else inputs,
            team_id=self.team.pk,
            source_id="source",
            connection_id="connection",
            status="Running",
            source_type=ExternalDataSourceType.POSTGRES,
        )

    def _rows(self) -> Any:
        return Integration.objects.filter(team_id=self.team.pk, kind="warehouse-source")

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

        assert not self._rows().exists()
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))["password"] == "fake-rotated"

    def test_create_and_save_mirror_only_the_connection_fields(self) -> None:
        with self._flag(return_value=True):
            source = self._create()
            row = self._rows().get()
            assert row.integration_id == str(source.id)
            assert row.config == {"source_type": "Postgres", "source_id": str(source.id)}
            assert row.sensitive_config == {"fields": POSTGRES_CONNECTION_FIELDS}

            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        row.refresh_from_db()
        assert row.sensitive_config == {"fields": {**POSTGRES_CONNECTION_FIELDS, "password": "fake-rotated"}}
        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))["password"] == "fake-rotated"

    def test_upsert_failure_does_not_block_the_job_inputs_save(self) -> None:
        before = _sample("posthog_warehouse_source_credentials_dual_write_total", {"outcome": "upsert_error"})
        with (
            self._flag(return_value=True),
            patch.object(WarehouseSourceCredentialsStore, "upsert", side_effect=RuntimeError("store down")),
        ):
            source = self._create()
            SourceInputsStore.save(source, {**STORED_POSTGRES_INPUTS, "password": "fake-rotated"})

        assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))["password"] == "fake-rotated"
        after = _sample("posthog_warehouse_source_credentials_dual_write_total", {"outcome": "upsert_error"})
        assert after - before == 2

    def test_update_runtime_does_not_touch_the_integration(self) -> None:
        with self._flag(return_value=True):
            source = self._create()
            self._rows().delete()

            SourceInputsStore.update_runtime(source, {"cdc_consistent_point": "0/16B3748"})

        assert not self._rows().exists()

    @parameterized.expand(
        [
            ("match", lambda rows, source: None, "match"),
            ("missing_row", lambda rows, source: rows.delete(), "missing_row"),
            ("unreadable", lambda rows, source: rows.update(sensitive_config={}), "unreadable"),
            (
                "field_mismatch",
                lambda rows, source: WarehouseSourceCredentialsStore.upsert(
                    source, {**POSTGRES_CONNECTION_FIELDS, "password": "fake-other"}
                ),
                "field_mismatch",
            ),
        ]
    )
    def test_shadow_compare_counts_the_result_and_keeps_the_returned_value(
        self, _name: str, change_row: Callable[[Any, ExternalDataSource], Any], expected_result: str
    ) -> None:
        with self._flag(return_value=True):
            source = self._create()
            change_row(self._rows(), source)

            for load in (
                lambda: SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)),
                lambda: SourceInputsStore.load_many([ExternalDataSource.objects.get(pk=source.pk)])[source.id],
            ):
                reset_caches()
                before = _compare_count(expected_result)
                assert load() == STORED_POSTGRES_INPUTS
                assert _compare_count(expected_result) - before == 1

    def test_shadow_compare_runs_once_per_interval_for_a_source(self) -> None:
        with self._flag(return_value=True):
            source = self._create()
            before = _compare_count("match")

            for _ in range(3):
                SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk))

        assert _compare_count("match") - before == 1

    def test_shadow_compare_never_raises(self) -> None:
        with (
            self._flag(return_value=True),
            patch.object(WarehouseSourceCredentialsStore, "get", side_effect=RuntimeError("store down")),
            patch.object(WarehouseSourceCredentialsStore, "get_many", side_effect=RuntimeError("store down")),
        ):
            source = self._create()
            assert SourceInputsStore.load(ExternalDataSource.objects.get(pk=source.pk)) == STORED_POSTGRES_INPUTS
            reset_caches()
            assert SourceInputsStore.load_many([source]) == {source.id: STORED_POSTGRES_INPUTS}
