import io

from django.test import SimpleTestCase, override_settings

import pandas as pd
from parameterized import parameterized

from products.warehouse_sources.backend.file_uploads import (
    ExcelConversionError,
    build_file_upload_url_pattern,
    excel_stored_filename,
    excel_to_parquet_bytes,
)


class TestBuildFileUploadUrlPattern(SimpleTestCase):
    @parameterized.expand(
        [
            # Local objectstorage is a path-style HTTP endpoint: bucket is the first path segment.
            ("local_http", True, "http://objectstorage:19000/data-warehouse/file_uploads/team_7/u1/data.parquet"),
            # Prod keeps https but is still path-style — the bucket must be in the path (its absence
            # is what made ClickHouse look in the wrong bucket and 404).
            ("prod_https", False, "https://objectstorage:19000/data-warehouse/file_uploads/team_7/u1/data.parquet"),
        ]
    )
    def test_bucket_is_first_path_segment_and_scheme_matches_env(self, _name: str, use_local: bool, expected: str):
        with override_settings(
            USE_LOCAL_SETUP=use_local,
            DATAWAREHOUSE_BUCKET="data-warehouse",
            DATAWAREHOUSE_BUCKET_DOMAIN="objectstorage:19000",
        ):
            assert build_file_upload_url_pattern(7, "u1", "data.parquet") == expected


def _xlsx_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


class TestExcelStoredFilename(SimpleTestCase):
    @parameterized.expand(
        [
            ("sales.xlsx", "sales.parquet"),
            ("sales.xlsm", "sales.parquet"),
            ("q1.report.xlsx", "q1.report.parquet"),
            ("noext", "noext.parquet"),
            ("", "upload.parquet"),
        ]
    )
    def test_maps_to_parquet_name(self, original: str, expected: str) -> None:
        assert excel_stored_filename(original) == expected


class TestExcelToParquet(SimpleTestCase):
    def test_first_sheet_round_trips_columns_and_values(self) -> None:
        frame = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})

        restored = pd.read_parquet(io.BytesIO(excel_to_parquet_bytes(_xlsx_bytes(frame))))

        assert list(restored.columns) == ["id", "name"]
        assert restored["id"].tolist() == [1, 2]
        assert restored["name"].tolist() == ["a", "b"]

    def test_only_the_first_sheet_is_converted(self) -> None:
        # Locks the documented one-workbook-one-table contract: a multi-sheet workbook must not
        # silently fold every sheet in, nor read the wrong one.
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            pd.DataFrame({"first": [1]}).to_excel(writer, sheet_name="S1", index=False)
            pd.DataFrame({"second": [2]}).to_excel(writer, sheet_name="S2", index=False)

        restored = pd.read_parquet(io.BytesIO(excel_to_parquet_bytes(buffer.getvalue())))

        assert list(restored.columns) == ["first"]

    def test_unreadable_bytes_raise_conversion_error(self) -> None:
        with self.assertRaises(ExcelConversionError):
            excel_to_parquet_bytes(b"this is not a workbook")

    def test_sheet_without_columns_raises_conversion_error(self) -> None:
        with self.assertRaises(ExcelConversionError):
            excel_to_parquet_bytes(_xlsx_bytes(pd.DataFrame()))
