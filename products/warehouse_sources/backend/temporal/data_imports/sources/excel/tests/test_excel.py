import io

from unittest.mock import patch

from django.test import SimpleTestCase

from openpyxl import Workbook
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.excel.excel import (
    ExcelReadError,
    dedupe_headers,
    list_sheets,
    read_sheet_rows,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.excel.excel"


def _workbook_bytes(sheets: dict[str, list[list]]) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class _FakeS3:
    """Stands in for the object store: serves the workbook bytes the source would read."""

    def __init__(self, data: bytes | None) -> None:
        self._data = data
        self.opened: list[str] = []

    def open(self, path: str, mode: str):
        self.opened.append(path)
        if self._data is None:
            raise FileNotFoundError(path)
        return io.BytesIO(self._data)

    def exists(self, path: str) -> bool:
        return self._data is not None


class TestDedupeHeaders(SimpleTestCase):
    @parameterized.expand(
        [
            ("plain", ("a", "b"), ["a", "b"]),
            ("blank_cells_get_positional_names", ("a", None, "  "), ["a", "column_2", "column_3"]),
            ("repeats_get_suffixed", ("a", "a", "a"), ["a", "a_2", "a_3"]),
            # A header already containing the suffixed form must not collide onto it — naive
            # per-base counting yields two "A_2" columns, which the table can't have.
            ("existing_suffix_is_skipped", ("A", "A_2", "A"), ["A", "A_2", "A_3"]),
        ]
    )
    def test_produces_unique_names(self, _name: str, header: tuple, expected: list[str]) -> None:
        result = dedupe_headers(header)
        assert result == expected
        assert len(set(result)) == len(result)


class TestListSheets(SimpleTestCase):
    def test_returns_every_sheet_with_its_columns(self) -> None:
        # One sheet per table is the whole point of routing Excel through the pipeline, so each
        # sheet must be discovered with the header names the column picker will show.
        data = _workbook_bytes({"Orders": [["id", "total"], [1, 10]], "Refunds": [["id", "reason"], [2, "x"]]})

        with patch(f"{MODULE}.get_s3_client", return_value=_FakeS3(data)):
            sheets = list_sheets(team_id=1, upload_id="u1", filename="book.xlsx")

        assert sheets == [("Orders", ["id", "total"]), ("Refunds", ["id", "reason"])]

    def test_skips_sheets_without_a_header_row(self) -> None:
        # An empty sheet would otherwise become an unimportable table in the picker.
        data = _workbook_bytes({"Empty": [], "Orders": [["id"], [1]]})

        with patch(f"{MODULE}.get_s3_client", return_value=_FakeS3(data)):
            sheets = list_sheets(team_id=1, upload_id="u1", filename="book.xlsx")

        assert [name for name, _ in sheets] == ["Orders"]

    def test_missing_object_raises_a_user_facing_error(self) -> None:
        with patch(f"{MODULE}.get_s3_client", return_value=_FakeS3(None)):
            with self.assertRaises(ExcelReadError):
                list_sheets(team_id=1, upload_id="u1", filename="book.xlsx")

    def test_unreadable_bytes_raise_a_user_facing_error(self) -> None:
        with patch(f"{MODULE}.get_s3_client", return_value=_FakeS3(b"not a workbook")):
            with self.assertRaises(ExcelReadError):
                list_sheets(team_id=1, upload_id="u1", filename="book.xlsx")


class TestReadSheetRows(SimpleTestCase):
    def _rows(self, data: bytes, sheet: str, enabled_columns: list[str] | None = None) -> list[dict]:
        with patch(f"{MODULE}.get_s3_client", return_value=_FakeS3(data)):
            return [row for chunk in read_sheet_rows(1, "u1", "book.xlsx", sheet, enabled_columns) for row in chunk]

    def test_yields_rows_keyed_by_header_preserving_cell_types(self) -> None:
        # Native types are why this beats a CSV round-trip: ints must not arrive as strings.
        data = _workbook_bytes({"Orders": [["id", "name"], [1, "a"], [2, "b"]]})

        rows = self._rows(data, "Orders")

        assert rows == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]

    def test_reads_only_the_requested_sheet(self) -> None:
        data = _workbook_bytes({"Orders": [["id"], [1]], "Refunds": [["ref"], [9]]})

        assert self._rows(data, "Refunds") == [{"ref": 9}]

    def test_enabled_columns_projects_the_row(self) -> None:
        # supports_column_selection = True is a promise the reader has to keep, or a deselected
        # column would still be synced.
        data = _workbook_bytes({"Orders": [["id", "name", "total"], [1, "a", 10]]})

        assert self._rows(data, "Orders", enabled_columns=["id", "total"]) == [{"id": 1, "total": 10}]

    def test_ragged_rows_pad_missing_trailing_cells(self) -> None:
        data = _workbook_bytes({"Orders": [["id", "name"], [1]]})

        assert self._rows(data, "Orders") == [{"id": 1, "name": None}]

    def test_unknown_sheet_raises_a_user_facing_error(self) -> None:
        data = _workbook_bytes({"Orders": [["id"], [1]]})

        with self.assertRaises(ExcelReadError):
            self._rows(data, "Missing")

    def test_chunks_rows_rather_than_materializing_the_sheet(self) -> None:
        data = _workbook_bytes({"Orders": [["id"], *[[i] for i in range(2500)]]})

        with patch(f"{MODULE}.get_s3_client", return_value=_FakeS3(data)), patch(f"{MODULE}.ROW_CHUNK", 1000):
            chunks = list(read_sheet_rows(1, "u1", "book.xlsx", "Orders"))

        assert [len(chunk) for chunk in chunks] == [1000, 1000, 500]
