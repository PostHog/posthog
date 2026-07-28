import uuid
from types import SimpleNamespace

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres import backfill_snapshot
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill_snapshot import (
    delta_table_uri,
)

_SCHEMA_ID = uuid.UUID("0190c6a4-6641-0000-0f7a-d9482771b742")


@override_settings(BUCKET_URL="s3://test-bucket/dlt")
class TestDeltaTableUri(SimpleTestCase):
    def _schema(self, name: str, leaf: str | None) -> ExternalDataSchema:
        # Built in memory (no save): exercises the real normalized_name and
        # folder_path. leaf=None models a schema with no catalog table yet.
        schema = ExternalDataSchema(id=_SCHEMA_ID, team_id=1, name=name)
        schema.source = ExternalDataSource(source_type="Postgres")
        if leaf is None:
            schema.table = None
        else:
            url = f"https://bucket.s3.amazonaws.com/dlt/{schema.folder_path()}/{leaf}"
            schema.table = DataWarehouseTable(url_pattern=url)
        return schema

    @parameterized.expand(
        [
            # Schema-qualified Postgres source: the loader wrote the Delta folder
            # under the unqualified table name, but normalized_name keeps the
            # "public_" qualifier. Reading normalized_name pointed the backfill at
            # a prefix with no _delta_log ("No files in log segment").
            ("schema_qualified", "public.posthog_hogfunction", "posthog_hogfunction/", "posthog_hogfunction"),
            # Unqualified name: folder and normalized_name already agree.
            (
                "unqualified",
                "campaign_performance_report",
                "campaign_performance_report/",
                "campaign_performance_report",
            ),
            # url_pattern may carry a trailing glob token instead of a bare slash.
            ("glob_suffix", "public.posthog_team", "posthog_team/*", "posthog_team"),
        ]
    )
    def test_uri_folder_comes_from_url_pattern_not_normalized_name(
        self, _name: str, schema_name: str, leaf: str, expected_leaf: str
    ) -> None:
        schema = self._schema(schema_name, leaf)

        uri = delta_table_uri(schema)

        assert uri == f"s3://test-bucket/dlt/{schema.folder_path()}/{expected_leaf}"

    def test_falls_back_to_normalized_name_when_no_table(self) -> None:
        schema = self._schema("public.posthog_hogfunction", leaf=None)

        uri = delta_table_uri(schema)

        assert uri == f"s3://test-bucket/dlt/{schema.folder_path()}/{schema.normalized_name}"

    def test_injected_url_pattern_leaf_cannot_escape_schema_prefix(self) -> None:
        # url_pattern is a user-writable field. A leaf crafted with encoded
        # separators (percent-encoded slashes survive split("/") as one segment)
        # must not let the backfill target a prefix outside the schema's folder.
        schema = self._schema("public.posthog_hogfunction", leaf="..%2f..%2fteam_2_postgres_secret%2fusers")

        uri = delta_table_uri(schema)

        prefix = f"s3://test-bucket/dlt/{schema.folder_path()}/"
        assert uri.startswith(prefix)
        leaf = uri[len(prefix) :]
        assert "/" not in leaf and "." not in leaf and "%" not in leaf


class _FakeColumn:
    def __init__(self, values: list) -> None:
        self._values = values

    def to_pylist(self) -> list:
        return self._values


class _FakeAddActions:
    def column(self, name: str) -> _FakeColumn:
        return {
            "path": _FakeColumn(["f.parquet"]),
            "size_bytes": _FakeColumn([100]),
            "num_records": _FakeColumn([10]),
        }[name]


class _FakeDeltaTable:
    # Stands in for deltalake.DeltaTable: counts real constructions so the
    # cache test can assert a pinned version's Delta log is read only once.
    instances = 0

    def __init__(self, uri: str, version: int | None = None, storage_options: dict | None = None) -> None:
        _FakeDeltaTable.instances += 1
        self._version = version if version is not None else 42

    def version(self) -> int:
        return self._version

    def protocol(self) -> SimpleNamespace:
        return SimpleNamespace(reader_features=[])

    def get_add_actions(self, flatten: bool = True) -> _FakeAddActions:
        return _FakeAddActions()

    def history(self) -> list[dict]:
        return []


@override_settings(BUCKET_URL="s3://test-bucket/dlt")
class TestResolveSnapshotPlanCaching(SimpleTestCase):
    # The reconciler re-resolves the same already-pinned snapshot_version on
    # every tick until a backfill drains; without a cache each call re-reads
    # the whole Delta commit log from S3 (dt.history() has no checkpoint
    # shortcut), which for a large table can trip S3 rate limiting.
    def setUp(self) -> None:
        backfill_snapshot._resolve_pinned_snapshot_plan.cache_clear()
        _FakeDeltaTable.instances = 0

    def _schema(self) -> ExternalDataSchema:
        schema = ExternalDataSchema(id=_SCHEMA_ID, team_id=1, name="orders")
        schema.source = ExternalDataSource(source_type="Postgres")
        schema.table = None
        return schema

    def test_pinned_version_is_resolved_once_across_repeated_calls(self) -> None:
        schema = self._schema()

        with patch("deltalake.DeltaTable", _FakeDeltaTable):
            first = backfill_snapshot.resolve_snapshot_plan(schema, version=5)
            second = backfill_snapshot.resolve_snapshot_plan(schema, version=5)

        assert _FakeDeltaTable.instances == 1
        assert first == second

    def test_different_pinned_versions_are_each_resolved(self) -> None:
        schema = self._schema()

        with patch("deltalake.DeltaTable", _FakeDeltaTable):
            backfill_snapshot.resolve_snapshot_plan(schema, version=5)
            backfill_snapshot.resolve_snapshot_plan(schema, version=6)

        assert _FakeDeltaTable.instances == 2

    def test_unpinned_head_version_is_never_cached(self) -> None:
        schema = self._schema()

        with patch("deltalake.DeltaTable", _FakeDeltaTable):
            backfill_snapshot.resolve_snapshot_plan(schema)
            backfill_snapshot.resolve_snapshot_plan(schema)

        assert _FakeDeltaTable.instances == 2
