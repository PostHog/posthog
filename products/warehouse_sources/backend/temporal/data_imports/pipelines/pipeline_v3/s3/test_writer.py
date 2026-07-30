import json

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.writer import build_schema_dict


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
