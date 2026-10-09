import io
import gzip
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing import (
    FORMAT_ERROR,
    FileDelimiterError,
    FileFormatError,
    ResolvedFormat,
    iter_file_rows,
    normalize_delimiter,
    resolve_file_format,
)


def csv_stream(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


class TestDelimiterNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (None, None),
            ("", None),
            (",", ","),
            (";", ";"),
            ("\t", "\t"),
            ("\\t", "\t"),
            ("tab", "\t"),
        ],
    )
    def test_normalize_delimiter(self, raw: str | None, expected: str | None) -> None:
        assert normalize_delimiter(raw) == expected

    def test_normalize_delimiter_rejects_multiple_characters(self) -> None:
        with pytest.raises(FileDelimiterError, match="single character"):
            normalize_delimiter("||")


class TestResolveFileFormat:
    @pytest.mark.parametrize(
        ("relative_path", "expected"),
        [
            ("orders.csv", ResolvedFormat("csv", ",", False)),
            ("orders.CSV", ResolvedFormat("csv", ",", False)),
            ("orders.tsv", ResolvedFormat("csv", "\t", False)),
            ("orders.txt", ResolvedFormat("csv", ",", False)),
            ("orders.jsonl", ResolvedFormat("jsonl", ",", False)),
            ("orders.ndjson", ResolvedFormat("jsonl", ",", False)),
            ("orders.json", ResolvedFormat("json", ",", False)),
            ("orders.csv.gz", ResolvedFormat("csv", ",", True)),
            ("orders.jsonl.gz", ResolvedFormat("jsonl", ",", True)),
        ],
    )
    def test_infers_from_extension(self, relative_path: str, expected: ResolvedFormat) -> None:
        assert resolve_file_format(relative_path, "infer") == expected

    def test_explicit_format_wins_over_extension(self) -> None:
        assert resolve_file_format("orders.txt", "jsonl") == ResolvedFormat("jsonl", ",", False)

    def test_explicit_delimiter_wins_over_extension_default(self) -> None:
        assert resolve_file_format("orders.tsv", "infer", ";") == ResolvedFormat("csv", ";", False)

    def test_unknown_extension_without_explicit_format_raises(self) -> None:
        with pytest.raises(FileFormatError, match=FORMAT_ERROR):
            resolve_file_format("orders.parquet", "infer")


class TestIterFileRows:
    def test_csv_headers_are_normalized_and_deduplicated(self) -> None:
        stream = csv_stream("Order Total (USD),name,Name\n1,a,b\n")

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", ",", False), "orders.csv"))

        assert chunks == [[{"order_total_usd": "1", "name": "a", "name_2": "b"}]]

    def test_csv_quoting_and_blank_lines(self) -> None:
        stream = csv_stream('a,b\n"x,y",2\n\n"multi\nline",3\n')

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", ",", False), "orders.csv"))

        assert chunks == [[{"a": "x,y", "b": "2"}, {"a": "multi\nline", "b": "3"}]]

    def test_csv_short_rows_are_padded(self) -> None:
        stream = csv_stream("a,b,c\n1,2\n")

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", ",", False), "orders.csv"))

        assert chunks == [[{"a": "1", "b": "2", "c": None}]]

    def test_csv_rows_with_extra_values_are_skipped_and_logged(self) -> None:
        stream = csv_stream("a,b\n1,2\n1,2,3\n")
        logger = MagicMock()

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", ",", False), "orders.csv", logger=logger))

        assert chunks == [[{"a": "1", "b": "2"}]]
        assert logger.warning.called

    def test_csv_uses_the_configured_delimiter(self) -> None:
        stream = csv_stream("a\tb\n1\t2\n")

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", "\t", False), "orders.tsv"))

        assert chunks == [[{"a": "1", "b": "2"}]]

    def test_gzipped_csv_is_decompressed(self) -> None:
        stream = io.BytesIO(gzip.compress(b"a,b\n1,2\n"))

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", ",", True), "orders.csv.gz"))

        assert chunks == [[{"a": "1", "b": "2"}]]

    def test_rows_are_chunked(self) -> None:
        stream = csv_stream("a\n1\n2\n3\n4\n5\n")

        chunks = list(iter_file_rows(stream, ResolvedFormat("csv", ",", False), "orders.csv", chunk_size=2))

        assert [len(chunk) for chunk in chunks] == [2, 2, 1]

    @pytest.mark.parametrize(
        ("payload", "file_format", "expected"),
        [
            (b'{"id": 1}\n{"id": 2}\n', "jsonl", [{"id": 1}, {"id": 2}]),
            (b'\n{"id": 1}\n\n', "jsonl", [{"id": 1}]),
            (b'[{"id": 1}, {"id": 2}]\n', "jsonl", [{"id": 1}, {"id": 2}]),
            (b'[{"id": 1}, {"id": 2}]', "json", [{"id": 1}, {"id": 2}]),
            (b'{"id": 1}', "json", [{"id": 1}]),
            (b'["a", "b"]', "json", [{"value": "a"}, {"value": "b"}]),
        ],
    )
    def test_json_shapes(self, payload: bytes, file_format: str, expected: list[dict[str, Any]]) -> None:
        resolved = ResolvedFormat(cast(Any, file_format), ",", False)

        chunks = list(iter_file_rows(io.BytesIO(payload), resolved, "orders.json"))

        assert [row for chunk in chunks for row in chunk] == expected

    def test_malformed_jsonl_line_reports_its_line_number(self) -> None:
        stream = io.BytesIO(b'{"id": 1}\nnot json\n')

        with pytest.raises(FileFormatError, match="Line 2"):
            list(iter_file_rows(stream, ResolvedFormat("jsonl", ",", False), "orders.jsonl"))

    def test_malformed_json_document_points_at_json_lines(self) -> None:
        stream = io.BytesIO(b'{"id": 1}\n{"id": 2}\n')

        with pytest.raises(FileFormatError, match="JSON Lines"):
            list(iter_file_rows(stream, ResolvedFormat("json", ",", False), "orders.json"))

    def test_json_chunking(self) -> None:
        stream = io.BytesIO(b"[1, 2, 3]")

        chunks = list(iter_file_rows(stream, ResolvedFormat("json", ",", False), "orders.json", chunk_size=2))

        assert [len(chunk) for chunk in chunks] == [2, 1]

    def test_oversized_json_document_is_rejected_before_it_is_parsed(self) -> None:
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.common.file_parsing"
        stream = io.BytesIO(b"[" + b"0," * 100 + b"0]")

        with patch(f"{module}.MAX_JSON_DOCUMENT_BYTES", 8):
            with pytest.raises(FileFormatError, match="single JSON document"):
                list(iter_file_rows(stream, ResolvedFormat("json", ",", False), "orders.json"))
