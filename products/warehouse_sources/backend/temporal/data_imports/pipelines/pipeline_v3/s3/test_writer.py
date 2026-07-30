import json
from typing import cast

from unittest.mock import MagicMock, patch

import pyarrow as pa
import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer import (
    S3BatchWriter,
    build_schema_dict,
)


class TestBuildSchemaDict:
    def test_field_metadata_is_json_serializable(self) -> None:
        schema = pa.schema([pa.field("id", pa.int64(), metadata={"comment": "primary key"})])

        schema_dict = build_schema_dict(schema)

        # Would raise "keys must be str ... not bytes" if the bytes metadata wasn't decoded.
        json.dumps(schema_dict)
        assert schema_dict["fields"][0]["metadata"] == {"comment": "primary key"}

    def test_field_without_metadata_stays_none(self) -> None:
        schema = pa.schema([pa.field("id", pa.int64())])

        assert build_schema_dict(schema)["fields"][0]["metadata"] is None


class TestWriteBatchSchemaAccumulation:
    def test_conflicting_column_types_across_batches_do_not_fail_the_write(self) -> None:
        # A vendor sending the same id as int in one page and string in the next used to abort the
        # whole table's sync with ArrowTypeError when the batch schemas were folded together.
        job = MagicMock(team_id=1, created_at=None)
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.get_date_partition",
                return_value="2026-07-30",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.ensure_bucket"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.get_s3_client"
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer.pq.write_table"
            ),
        ):
            writer = S3BatchWriter(
                cast(FilteringBoundLogger, structlog.get_logger()), job, schema_id="s1", run_uuid="run-1"
            )

            writer.write_batch(pa.table({"owner_id": pa.array([1], type=pa.int64())}), batch_index=0)
            writer.write_batch(pa.table({"owner_id": pa.array(["2"], type=pa.string())}), batch_index=1)

        schema = writer.get_schema()
        assert schema is not None
        assert schema.field("owner_id").type == pa.string()
