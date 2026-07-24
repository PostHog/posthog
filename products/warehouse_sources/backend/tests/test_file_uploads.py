import io

from django.test import SimpleTestCase

import pandas as pd
from parameterized import parameterized

from products.warehouse_sources.backend.file_uploads import (
    ExcelConversionError,
    excel_stored_filename,
    excel_to_parquet_bytes,
)


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
