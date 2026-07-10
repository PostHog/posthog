import uuid

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
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
