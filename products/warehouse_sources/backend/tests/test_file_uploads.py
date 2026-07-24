import io

from unittest.mock import patch

from django.test import SimpleTestCase

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from parameterized import parameterized

from products.warehouse_sources.backend.file_uploads import (
    ExcelConversionError,
    _dedupe_excel_headers,
    excel_stored_filename,
    excel_to_parquet_bytes,
)

MODULE = "products.warehouse_sources.backend.file_uploads"


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


class TestDedupeExcelHeaders(SimpleTestCase):
    @parameterized.expand(
        [
            ("blank_cells_become_positional", (None, "", "  "), ["column_1", "column_2", "column_3"]),
            ("repeats_get_suffixes", ("a", "a", "a"), ["a", "a_2", "a_3"]),
            # A suffixed fallback must not collide with a literal name already in the row: naive
            # per-base counting turns this into ["A", "A_2", "A_2"], which Parquet/ClickHouse reject.
            ("suffix_avoids_existing_name", ("A", "A_2", "A"), ["A", "A_2", "A_3"]),
        ]
    )
    def test_produces_unique_names(self, _name: str, header: tuple, expected: list[str]) -> None:
        result = _dedupe_excel_headers(header)
        assert result == expected
        assert len(set(result)) == len(result)


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

    def test_rejects_archive_that_decompresses_past_the_budget(self) -> None:
        # A zip bomb declares a huge uncompressed size; the pre-check rejects it before openpyxl runs.
        with patch(f"{MODULE}.MAX_EXCEL_UNCOMPRESSED_BYTES", 1):
            with self.assertRaises(ExcelConversionError):
                excel_to_parquet_bytes(_xlsx_bytes(pd.DataFrame({"id": [1]})))

    def test_rejects_too_many_columns(self) -> None:
        with patch(f"{MODULE}.MAX_EXCEL_COLUMNS", 2):
            with self.assertRaises(ExcelConversionError):
                excel_to_parquet_bytes(_xlsx_bytes(pd.DataFrame({"a": [1], "b": [2], "c": [3]})))

    def test_rejects_too_many_rows(self) -> None:
        # Cell budget of 4 over 2 columns → at most 2 rows; a 3-row sheet trips the guard.
        with patch(f"{MODULE}.MAX_EXCEL_CELLS", 4):
            with self.assertRaises(ExcelConversionError):
                excel_to_parquet_bytes(_xlsx_bytes(pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})))

    def test_all_empty_column_becomes_readable_string_not_null(self) -> None:
        # An all-blank column (e.g. formulas with no cached values) would infer pyarrow `null`, which
        # ClickHouse can't introspect from Parquet — it must land as a nullable string instead.
        frame = pd.DataFrame({"id": [1, 2], "notes": [None, None]})

        schema = pq.read_table(io.BytesIO(excel_to_parquet_bytes(_xlsx_bytes(frame)))).schema

        assert pa.types.is_string(schema.field("notes").type)
