import io
import re
import csv
import gzip
import json
import posixpath
import dataclasses
from collections.abc import Iterator
from typing import IO, Any, Literal, cast

from structlog.types import FilteringBoundLogger

FileFormat = Literal["csv", "jsonl", "json"]
ConfiguredFileFormat = Literal["infer", "csv", "jsonl", "json"]

# A whole-document JSON file has to be materialized to parse it, so cap how many decompressed bytes
# we read before giving up and steering the user to JSON Lines (which streams). Also stops a small
# gzip file from decompressing into unbounded memory.
MAX_JSON_DOCUMENT_BYTES = 256 * 1024 * 1024

CHUNK_SIZE = 5000

# Every row carries which file it came from, so a table built from many files stays traceable.
FILE_PATH_COLUMN = "_file_name"
FILE_MODIFIED_AT_COLUMN = "_file_modified_at"

EXTENSION_FORMATS: dict[str, FileFormat] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".json": "json",
}

EXTENSION_DELIMITERS: dict[str, str] = {".tsv": "\t"}

DEFAULT_DELIMITER = ","

FORMAT_ERROR = "Can't work out the format of the remote file"
DELIMITER_ERROR = "The CSV delimiter must be a single character"


class FileFormatError(Exception):
    """A file could not be parsed with the configured or inferred format."""


class FileDelimiterError(ValueError):
    """The configured delimiter is not a single character."""


@dataclasses.dataclass(frozen=True)
class ResolvedFormat:
    file_format: FileFormat
    delimiter: str
    compressed: bool


def normalize_delimiter(delimiter: str | None) -> str | None:
    """Accept a literal tab, an escaped `\\t`, or the word `tab` for tab-separated files."""
    if delimiter is None:
        return None
    if delimiter in ("\\t", "tab", "\t"):
        return "\t"
    if delimiter == "":
        return None
    if len(delimiter) != 1:
        raise FileDelimiterError(f"{DELIMITER_ERROR} (got {delimiter!r}). Use \\t for tab-separated files.")
    return delimiter


def is_format_inferable(relative_path: str) -> bool:
    lowered = relative_path.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[: -len(".gz")]
    return posixpath.splitext(lowered)[1] in EXTENSION_FORMATS


def resolve_file_format(
    relative_path: str,
    configured_format: ConfiguredFileFormat | str | None = "infer",
    delimiter: str | None = None,
) -> ResolvedFormat:
    lowered = relative_path.lower()
    compressed = lowered.endswith(".gz")
    if compressed:
        lowered = lowered[: -len(".gz")]
    extension = posixpath.splitext(lowered)[1]

    if configured_format and configured_format != "infer":
        file_format = cast(FileFormat, configured_format)
    else:
        inferred = EXTENSION_FORMATS.get(extension)
        if inferred is None:
            raise FileFormatError(
                f"{FORMAT_ERROR} '{relative_path}'. Set the file format explicitly, or restrict the file "
                "pattern to .csv, .json, or .jsonl files."
            )
        file_format = inferred

    resolved_delimiter = normalize_delimiter(delimiter) or EXTENSION_DELIMITERS.get(extension, DEFAULT_DELIMITER)
    return ResolvedFormat(file_format=file_format, delimiter=resolved_delimiter, compressed=compressed)


def normalize_column_name(header: str) -> str:
    """Headers like 'Order Total (USD)' become stable snake_case columns."""
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", header).strip("_").lower()
    return normalized or "column"


def dedupe_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for header in headers:
        name = normalize_column_name(header)
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        result.append(name)
    return result


def _decompressed_stream(stream: IO[bytes], compressed: bool) -> IO[bytes]:
    return cast(IO[bytes], gzip.GzipFile(fileobj=stream)) if compressed else stream


def _text_stream(binary: IO[bytes]) -> IO[str]:
    return io.TextIOWrapper(binary, encoding="utf-8", errors="replace", newline="")


def _iter_csv_rows(
    text: IO[str],
    delimiter: str,
    relative_path: str,
    chunk_size: int,
    logger: FilteringBoundLogger | None,
) -> Iterator[list[dict[str, Any]]]:
    reader = csv.reader(text, delimiter=delimiter)
    headers: list[str] | None = None
    chunk: list[dict[str, Any]] = []

    for line_number, row in enumerate(reader, start=1):
        if headers is None:
            headers = dedupe_headers(row)
            continue
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(headers):
            # More values than headers means the file is malformed or the delimiter is wrong.
            # Dropping the row keeps the extra values from silently landing in the wrong columns.
            if logger is not None:
                logger.warning(
                    "Skipping CSV row with more values than headers",
                    file=relative_path,
                    line=line_number,
                    expected=len(headers),
                    got=len(row),
                )
            continue
        values: list[str | None] = [*row, *([None] * (len(headers) - len(row)))]
        chunk.append(dict(zip(headers, values)))
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []

    if chunk:
        yield chunk


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item if isinstance(item, dict) else {"value": item} for item in value]
    return [{"value": value}]


def _iter_jsonl_rows(text: IO[str], relative_path: str, chunk_size: int) -> Iterator[list[dict[str, Any]]]:
    chunk: list[dict[str, Any]] = []
    for line_number, line in enumerate(text, start=1):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as e:
            raise FileFormatError(
                f"Line {line_number} of '{relative_path}' isn't valid JSON: {e}. If the file holds one "
                "JSON document rather than one object per line, set the file format to JSON."
            ) from e
        chunk.extend(_as_rows(parsed))
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _iter_json_rows(binary: IO[bytes], relative_path: str, chunk_size: int) -> Iterator[list[dict[str, Any]]]:
    # A whole-document JSON file can't be chunked, so it has to fit in memory. Read one decompressed
    # byte past the limit to detect an oversized (or gzip-bomb) document before materializing it, and
    # point the user at JSON Lines, which streams. The byte cap is what bounds memory here, so it runs
    # on the decompressed bytes rather than a decoded-character count.
    raw = binary.read(MAX_JSON_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_JSON_DOCUMENT_BYTES:
        raise FileFormatError(
            f"'{relative_path}' is larger than the {MAX_JSON_DOCUMENT_BYTES // (1024 * 1024)} MB limit for a "
            "single JSON document. Convert it to JSON Lines (one object per line) so it can stream in."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FileFormatError(
            f"'{relative_path}' isn't valid JSON: {e}. If the file holds one JSON object per line, "
            "set the file format to JSON Lines."
        ) from e

    rows = _as_rows(parsed)
    for start in range(0, len(rows), chunk_size):
        yield rows[start : start + chunk_size]


def iter_file_rows(
    stream: IO[bytes],
    resolved: ResolvedFormat,
    relative_path: str,
    chunk_size: int = CHUNK_SIZE,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[list[dict[str, Any]]]:
    binary = _decompressed_stream(stream, resolved.compressed)
    if resolved.file_format == "csv":
        yield from _iter_csv_rows(_text_stream(binary), resolved.delimiter, relative_path, chunk_size, logger)
    elif resolved.file_format == "jsonl":
        yield from _iter_jsonl_rows(_text_stream(binary), relative_path, chunk_size)
    else:
        yield from _iter_json_rows(binary, relative_path, chunk_size)
