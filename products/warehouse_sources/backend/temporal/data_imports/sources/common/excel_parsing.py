import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import IO, Any

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.workbook.workbook import Workbook
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    CHUNK_SIZE,
    dedupe_headers,
)

EXCEL_ERROR = "Can't read the Excel file"
MAX_EXCEL_FILE_BYTES = 100 * 1024 * 1024
MAX_SHARED_STRINGS_BYTES = 256 * 1024 * 1024
MAX_WORKBOOK_PART_BYTES = 64 * 1024 * 1024
MAX_WORKSHEET_BYTES = 1024 * 1024 * 1024

ExcelValue = int | float | bool | str | datetime | None


class ExcelFileError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(f"{EXCEL_ERROR} {message}")


@contextmanager
def _open_workbook(file: IO[bytes], file_name: str) -> Iterator[Workbook]:
    workbook = None
    try:
        try:
            file.seek(0)
            with zipfile.ZipFile(file) as archive:
                # openpyxl loads every part except the worksheets into memory, even in read-only mode.
                # It also holds each worksheet cell in memory whole, so worksheets get a larger limit.
                for part in archive.infolist():
                    if part.filename == "xl/sharedStrings.xml":
                        limit = MAX_SHARED_STRINGS_BYTES
                    elif part.filename.startswith("xl/worksheets/"):
                        limit = MAX_WORKSHEET_BYTES
                    else:
                        limit = MAX_WORKBOOK_PART_BYTES
                    if part.file_size > limit:
                        if part.filename == "xl/sharedStrings.xml":
                            raise ExcelFileError(
                                f"'{file_name}': shared strings exceed the size limit. Split the workbook."
                            )
                        raise ExcelFileError(
                            f"'{file_name}': '{part.filename}' exceeds the size limit. Split the workbook."
                        )
        finally:
            file.seek(0)
        # Cached results keep formulas out of the data. Uncached formulas read as None.
        workbook = openpyxl.load_workbook(file, read_only=True, data_only=True)
        yield workbook
    except (zipfile.BadZipFile, InvalidFileException, KeyError, SyntaxError, ValueError, OSError) as error:
        raise ExcelFileError(f"'{file_name}'. Save it as .xlsx again, then refresh the source's tables.") from error
    finally:
        if workbook is not None:
            workbook.close()


def list_worksheets(file: IO[bytes], file_name: str) -> list[str]:
    with _open_workbook(file, file_name) as workbook:
        return [ws.title for ws in workbook.worksheets if ws.sheet_state == "visible"]


def normalize_cell(value: object) -> ExcelValue:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if value is None or isinstance(value, (int, float, bool, str)):
        return value
    return str(value)


def normalize_chunk(rows: list[dict[str, ExcelValue]]) -> list[dict[str, ExcelValue]]:
    if not rows:
        return []
    mixed = set()
    for column in rows[0]:
        kinds = {
            float if type(value) in (int, float) else type(value) for row in rows if (value := row[column]) is not None
        }
        if len(kinds) > 1:
            mixed.add(column)
    return [
        {column: str(value) if column in mixed and value is not None else value for column, value in row.items()}
        for row in rows
    ]


def iter_worksheet_rows(
    file: IO[bytes],
    file_name: str,
    worksheet: str,
    chunk_size: int = CHUNK_SIZE,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[list[dict[str, Any]]]:
    with _open_workbook(file, file_name) as workbook:
        ws = next((sheet for sheet in workbook.worksheets if sheet.title == worksheet), None)
        if ws is None:
            raise ExcelFileError(
                f"'{file_name}' has no worksheet named '{worksheet}'. "
                "It may have been renamed or deleted. Refresh the source's tables."
            )
        # Other writers can leave dimensions that hide rows or add empty columns.
        ws.reset_dimensions()
        rows = ws.iter_rows(values_only=True)
        headers = [str(cell) if cell is not None else "" for cell in next(rows, ())]
        while headers and not headers[-1].strip():
            headers.pop()
        if not headers:
            return
        headers = dedupe_headers(headers)
        chunk: list[dict[str, ExcelValue]] = []
        for row in rows:
            values = list(row[: len(headers)])
            if all(value is None or (isinstance(value, str) and not value.strip()) for value in values):
                continue
            values.extend([None] * (len(headers) - len(values)))
            chunk.append(dict(zip(headers, map(normalize_cell, values))))
            if len(chunk) >= chunk_size:
                yield normalize_chunk(chunk)
                chunk = []
        if chunk:
            yield normalize_chunk(chunk)
