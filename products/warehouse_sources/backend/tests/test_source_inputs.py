import json
from typing import Any

from posthog.test.base import BaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.logic.source_inputs import SourceInputsStore, UnreadableSourceInputsError
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
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
