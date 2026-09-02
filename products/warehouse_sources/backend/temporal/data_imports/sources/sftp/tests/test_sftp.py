import io
import gzip
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from paramiko.file import BufferedFile

from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.settings import (
    FILE_MODIFIED_AT_COLUMN,
    FILE_PATH_COLUMN,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp import (
    AUTH_FAILED_ERROR,
    CONNECTION_FAILED_ERROR,
    DELIMITER_ERROR,
    DIRECTORY_ERROR,
    FORMAT_ERROR,
    NO_FILES_ERROR,
    NO_MATCHING_FILES_ERROR,
    PATTERN_ERROR,
    PRIVATE_KEY_ERROR,
    RemoteFile,
    ResolvedFormat,
    SFTPAuth,
    SFTPCredentialsError,
    SFTPFileFormatError,
    get_rows,
    group_files_by_table,
    iter_file_rows,
    iter_table_rows,
    list_remote_files,
    load_private_key,
    normalize_delimiter,
    normalize_remote_path,
    resolve_file_format,
    sftp_connection,
    sftp_source,
    table_name_for_file,
    validate_credentials,
)

DIRECTORY_MODE = stat.S_IFDIR | 0o755
FILE_MODE = stat.S_IFREG | 0o644
SYMLINK_MODE = stat.S_IFLNK | 0o777


class FakeAttributes:
    def __init__(self, filename: str, st_mode: int = FILE_MODE, st_size: int = 16, st_mtime: int = 1_700_000_000):
        self.filename = filename
        self.st_mode = st_mode
        self.st_size = st_size
        self.st_mtime = st_mtime


class BufferedRemoteHandle(BufferedFile):
    """Stands in for `paramiko.SFTPFile`, which is a `BufferedFile` rather than a `BytesIO`."""

    def __init__(self, data: bytes) -> None:
        super().__init__()
        self._set_mode("rb")  # type: ignore[attr-defined]
        self._source = io.BytesIO(data)

    def _read(self, size: int) -> bytes:
        return self._source.read(size)

    def prefetch(self, file_size: int | None = None) -> None:
        return None


class FakeRemoteHandle(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.prefetched: int | None = None

    def prefetch(self, file_size: int | None = None) -> None:
        self.prefetched = file_size


class FakeClient:
    def __init__(
        self,
        tree: dict[str, list[FakeAttributes]],
        contents: dict[str, bytes] | None = None,
        unreadable: set[str] | None = None,
        handle_factory: Callable[[bytes], Any] = FakeRemoteHandle,
    ) -> None:
        self.tree = tree
        self.contents = contents or {}
        self.unreadable = unreadable or set()
        self.handle_factory = handle_factory
        self.handles: list[Any] = []
        self.closed = False

    def listdir_attr(self, path: str) -> list[Any]:
        if path in self.unreadable:
            raise OSError(f"permission denied: {path}")
        if path not in self.tree:
            raise OSError(f"no such directory: {path}")
        return list(self.tree[path])

    def open(self, filename: str, mode: str = "r", bufsize: int = -1) -> Any:
        handle = self.handle_factory(self.contents[filename])
        self.handles.append(handle)
        return handle

    def close(self) -> None:
        self.closed = True


def make_file(relative_path: str, modified_at: datetime | None = None) -> RemoteFile:
    return RemoteFile(
        path=f"/data/{relative_path}",
        relative_path=relative_path,
        size=10,
        modified_at=modified_at or datetime(2024, 1, 1, tzinfo=UTC),
    )


def csv_stream(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


class TestPathAndDelimiterNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("/data", "/data"),
            ("/data/", "/data"),
            ("/data//sub/", "/data/sub"),
            ("/", "/"),
            ("", "."),
            ("   ", "."),
            (None, "."),
        ],
    )
    def test_normalize_remote_path(self, raw: str | None, expected: str) -> None:
        assert normalize_remote_path(raw) == expected

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
        with pytest.raises(SFTPCredentialsError, match="single character"):
            normalize_delimiter("||")


class TestListRemoteFiles:
    def _tree_client(self) -> FakeClient:
        return FakeClient(
            {
                "/data": [
                    FakeAttributes("top.csv"),
                    FakeAttributes("sub", st_mode=DIRECTORY_MODE),
                    FakeAttributes("notes.txt"),
                    FakeAttributes("link.csv", st_mode=SYMLINK_MODE),
                ],
                "/data/sub": [
                    FakeAttributes("nested.json"),
                    FakeAttributes("deeper", st_mode=DIRECTORY_MODE),
                ],
                "/data/sub/deeper": [FakeAttributes("deep.csv")],
            }
        )

    def test_walks_subdirectories_and_returns_sorted_relative_paths(self) -> None:
        files = list_remote_files(self._tree_client(), "/data/")

        assert [file.relative_path for file in files] == [
            "notes.txt",
            "sub/deeper/deep.csv",
            "sub/nested.json",
            "top.csv",
        ]
        assert files[-1].path == "/data/top.csv"
        assert files[-1].modified_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)

    def test_skips_entries_that_are_not_regular_files(self) -> None:
        files = list_remote_files(self._tree_client(), "/data")

        assert "link.csv" not in [file.relative_path for file in files]

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            (r"\.csv$", ["sub/deeper/deep.csv", "top.csv"]),
            (r"^sub/", ["sub/deeper/deep.csv", "sub/nested.json"]),
            (r"nested", ["sub/nested.json"]),
            (None, ["notes.txt", "sub/deeper/deep.csv", "sub/nested.json", "top.csv"]),
        ],
    )
    def test_filters_by_pattern(self, pattern: str | None, expected: list[str]) -> None:
        files = list_remote_files(self._tree_client(), "/data", pattern)

        assert [file.relative_path for file in files] == expected

    def test_rejects_invalid_pattern(self) -> None:
        with pytest.raises(SFTPCredentialsError, match=PATTERN_ERROR):
            list_remote_files(self._tree_client(), "/data", "([unclosed")

    def test_stops_at_max_depth(self) -> None:
        files = list_remote_files(self._tree_client(), "/data", max_depth=1)

        assert [file.relative_path for file in files] == ["notes.txt", "sub/nested.json", "top.csv"]

    def test_stops_at_max_files_and_warns(self) -> None:
        logger = MagicMock()

        files = list_remote_files(self._tree_client(), "/data", max_files=2, logger=logger)

        assert len(files) == 2
        assert logger.warning.called

    def test_stops_at_max_directories_and_warns(self) -> None:
        # `max_files` counts matching files only, so a pattern matching nothing has to be bounded by
        # the folder budget instead — otherwise a wide tree walks until the worker gives up.
        listings = 0

        class WideTree:
            def listdir_attr(self, path: str) -> list[Any]:
                nonlocal listings
                listings += 1
                return [FakeAttributes(f"d{index}", st_mode=DIRECTORY_MODE) for index in range(10)]

            def open(self, filename: str, mode: str = "r", bufsize: int = -1) -> Any:
                raise NotImplementedError

        logger = MagicMock()

        files = list_remote_files(WideTree(), "/data", pattern=r"\.csv$", max_directories=25, logger=logger)

        assert files == []
        assert listings == 25
        assert logger.warning.called

    def test_unreadable_root_is_a_credentials_error(self) -> None:
        client = FakeClient({"/data": []}, unreadable={"/data"})

        with pytest.raises(SFTPCredentialsError, match=DIRECTORY_ERROR):
            list_remote_files(client, "/data")

    def test_unreadable_subdirectory_is_skipped(self) -> None:
        client = FakeClient(
            {
                "/data": [FakeAttributes("top.csv"), FakeAttributes("locked", st_mode=DIRECTORY_MODE)],
                "/data/locked": [FakeAttributes("secret.csv")],
            },
            unreadable={"/data/locked"},
        )
        logger = MagicMock()

        files = list_remote_files(client, "/data", logger=logger)

        assert [file.relative_path for file in files] == ["top.csv"]
        assert logger.warning.called


class TestTableGrouping:
    @pytest.mark.parametrize(
        ("relative_path", "expected"),
        [
            ("orders.csv", "orders"),
            ("Orders 2024.csv", "orders_2024"),
            ("sub/dir/orders.json", "sub_dir_orders"),
            ("orders.csv.gz", "orders"),
            ("orders.CSV.GZ", "orders"),
            ("---.csv", "sftp_data"),
        ],
    )
    def test_table_name_for_file(self, relative_path: str, expected: str) -> None:
        assert table_name_for_file(relative_path) == expected

    def test_one_table_per_file(self) -> None:
        grouped = group_files_by_table([make_file("b.csv"), make_file("a.csv")])

        assert list(grouped) == ["a", "b"]
        assert [file.relative_path for file in grouped["a"]] == ["a.csv"]

    def test_colliding_names_are_deduplicated_deterministically(self) -> None:
        files = [make_file("2024/orders.csv"), make_file("orders.csv"), make_file("orders.json")]

        first = group_files_by_table(files)
        second = group_files_by_table(list(reversed(files)))

        assert list(first) == ["2024_orders", "orders", "orders_2"]
        assert first == second

    def test_combined_mode_puts_every_file_in_one_sanitized_table(self) -> None:
        grouped = group_files_by_table([make_file("a.csv"), make_file("b.csv")], combined_table_name="Daily Orders")

        assert list(grouped) == ["daily_orders"]
        assert [file.relative_path for file in grouped["daily_orders"]] == ["a.csv", "b.csv"]


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
        with pytest.raises(SFTPFileFormatError, match=FORMAT_ERROR):
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

        with pytest.raises(SFTPFileFormatError, match="Line 2"):
            list(iter_file_rows(stream, ResolvedFormat("jsonl", ",", False), "orders.jsonl"))

    def test_malformed_json_document_points_at_json_lines(self) -> None:
        stream = io.BytesIO(b'{"id": 1}\n{"id": 2}\n')

        with pytest.raises(SFTPFileFormatError, match="JSON Lines"):
            list(iter_file_rows(stream, ResolvedFormat("json", ",", False), "orders.json"))

    def test_json_chunking(self) -> None:
        stream = io.BytesIO(b"[1, 2, 3]")

        chunks = list(iter_file_rows(stream, ResolvedFormat("json", ",", False), "orders.json", chunk_size=2))

        assert [len(chunk) for chunk in chunks] == [2, 1]

    def test_oversized_json_document_is_rejected_before_it_is_parsed(self) -> None:
        module = "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp"
        stream = io.BytesIO(b"[" + b"0," * 100 + b"0]")

        with patch(f"{module}.MAX_JSON_DOCUMENT_BYTES", 8):
            with pytest.raises(SFTPFileFormatError, match="single JSON document"):
                list(iter_file_rows(stream, ResolvedFormat("json", ",", False), "orders.json"))


class TestIterTableRows:
    def test_adds_file_metadata_to_every_row_across_files(self) -> None:
        modified_at = datetime(2024, 3, 1, 12, tzinfo=UTC)
        files = [make_file("a.csv", modified_at), make_file("b.jsonl", modified_at)]
        client = FakeClient(
            {},
            contents={"/data/a.csv": b"id\n1\n", "/data/b.jsonl": b'{"id": 2}\n'},
        )

        rows = [row for chunk in iter_table_rows(client, files) for row in chunk]

        assert rows == [
            {"id": "1", FILE_PATH_COLUMN: "a.csv", FILE_MODIFIED_AT_COLUMN: modified_at},
            {"id": 2, FILE_PATH_COLUMN: "b.jsonl", FILE_MODIFIED_AT_COLUMN: modified_at},
        ]

    def test_prefetches_each_file(self) -> None:
        client = FakeClient({}, contents={"/data/a.csv": b"id\n1\n"})

        list(iter_table_rows(client, [make_file("a.csv")]))

        assert [handle.prefetched for handle in client.handles] == [10]

    def test_reads_a_paramiko_style_buffered_file(self) -> None:
        # paramiko hands back a `BufferedFile`, not a `BytesIO`, and parsing wraps it in a
        # `TextIOWrapper` — which only works while that class keeps its file-object surface.
        client = FakeClient({}, contents={"/data/a.csv": b"id\n1\n"}, handle_factory=BufferedRemoteHandle)

        rows = [row for chunk in iter_table_rows(client, [make_file("a.csv")]) for row in chunk]

        assert [row["id"] for row in rows] == ["1"]

    def test_unparseable_file_format_propagates(self) -> None:
        client = FakeClient({}, contents={"/data/a.parquet": b"junk"})

        with pytest.raises(SFTPFileFormatError):
            list(iter_table_rows(client, [make_file("a.parquet")]))


class TestSFTPConnection:
    def test_unreachable_host_is_a_credentials_error(self) -> None:
        with patch("socket.create_connection", side_effect=OSError("connection refused")):
            with pytest.raises(SFTPCredentialsError, match=CONNECTION_FAILED_ERROR):
                with sftp_connection(
                    host="sftp.example.com", port=22, user="posthog", auth=SFTPAuth(password="hunter2")
                ):
                    pass

    def test_rejected_credentials_are_a_credentials_error(self) -> None:
        transport = MagicMock()
        transport.connect.side_effect = paramiko.AuthenticationException("nope")

        with (
            patch("socket.create_connection", return_value=MagicMock()),
            patch("paramiko.Transport", return_value=transport),
        ):
            with pytest.raises(SFTPCredentialsError, match=AUTH_FAILED_ERROR):
                with sftp_connection(host="sftp.example.com", port=22, user="posthog", auth=SFTPAuth(password="wrong")):
                    pass

        transport.close.assert_called_once()

    def test_ssh_error_during_handshake_is_a_credentials_error(self) -> None:
        transport = MagicMock()
        transport.connect.side_effect = paramiko.SSHException("no matching kex")

        with (
            patch("socket.create_connection", return_value=MagicMock()),
            patch("paramiko.Transport", return_value=transport),
        ):
            with pytest.raises(SFTPCredentialsError, match=CONNECTION_FAILED_ERROR):
                with sftp_connection(
                    host="sftp.example.com", port=22, user="posthog", auth=SFTPAuth(password="hunter2")
                ):
                    pass

    def test_missing_sftp_subsystem_is_a_credentials_error(self) -> None:
        with (
            patch("socket.create_connection", return_value=MagicMock()),
            patch("paramiko.Transport", return_value=MagicMock()),
            patch("paramiko.SFTPClient.from_transport", return_value=None),
        ):
            with pytest.raises(SFTPCredentialsError, match="SFTP subsystem"):
                with sftp_connection(
                    host="sftp.example.com", port=22, user="posthog", auth=SFTPAuth(password="hunter2")
                ):
                    pass

    def test_closes_the_client_and_transport_on_success(self) -> None:
        transport = MagicMock()
        client = MagicMock()

        with (
            patch("socket.create_connection", return_value=MagicMock()),
            patch("paramiko.Transport", return_value=transport),
            patch("paramiko.SFTPClient.from_transport", return_value=client),
        ):
            with sftp_connection(
                host="sftp.example.com", port=22, user="posthog", auth=SFTPAuth(password="hunter2")
            ) as opened:
                assert opened is client

        client.close.assert_called_once()
        transport.close.assert_called_once()

    def test_connects_with_a_parsed_private_key(self) -> None:
        transport = MagicMock()

        with (
            patch("socket.create_connection", return_value=MagicMock()),
            patch("paramiko.Transport", return_value=transport),
            patch("paramiko.SFTPClient.from_transport", return_value=MagicMock()),
        ):
            with sftp_connection(
                host="sftp.example.com", port=22, user="posthog", auth=SFTPAuth(private_key=_generate_private_key())
            ):
                pass

        assert transport.connect.call_args.kwargs["pkey"] is not None
        assert transport.connect.call_args.kwargs["password"] is None


def _generate_private_key() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


class TestLoadPrivateKey:
    def test_parses_an_openssh_key(self) -> None:
        assert isinstance(load_private_key(_generate_private_key()), paramiko.PKey)

    @pytest.mark.parametrize("private_key", ["not-a-key", "", "-----BEGIN OPENSSH PRIVATE KEY-----\ntruncated\n"])
    def test_unreadable_key_is_a_credentials_error(self, private_key: str) -> None:
        with pytest.raises(SFTPCredentialsError, match=PRIVATE_KEY_ERROR):
            load_private_key(private_key)


@contextmanager
def _patched_connection(client: FakeClient) -> Iterator[FakeClient]:
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp.sftp_connection"
    ) as connection:
        connection.return_value.__enter__.return_value = client
        yield client


class TestGetRows:
    def _client(self) -> FakeClient:
        return FakeClient(
            {"/data": [FakeAttributes("orders.csv", st_size=10), FakeAttributes("refunds.csv", st_size=10)]},
            contents={"/data/orders.csv": b"id\n1\n", "/data/refunds.csv": b"id\n2\n"},
        )

    def test_yields_only_the_requested_table(self) -> None:
        with _patched_connection(self._client()):
            rows = [
                row
                for chunk in get_rows(
                    host="h", port=22, user="u", schema_name="orders", auth=SFTPAuth(password="p"), path="/data"
                )
                for row in chunk
            ]

        assert [row["id"] for row in rows] == ["1"]
        assert {row[FILE_PATH_COLUMN] for row in rows} == {"orders.csv"}

    def test_combined_table_reads_every_file(self) -> None:
        with _patched_connection(self._client()):
            rows = [
                row
                for chunk in get_rows(
                    host="h",
                    port=22,
                    user="u",
                    schema_name="all_orders",
                    auth=SFTPAuth(password="p"),
                    path="/data",
                    combined_table_name="all_orders",
                )
                for row in chunk
            ]

        assert [row["id"] for row in rows] == ["1", "2"]

    def test_missing_table_is_a_credentials_error(self) -> None:
        with _patched_connection(self._client()):
            with pytest.raises(SFTPCredentialsError, match=NO_FILES_ERROR):
                list(
                    get_rows(host="h", port=22, user="u", schema_name="gone", auth=SFTPAuth(password="p"), path="/data")
                )


class TestValidateCredentials:
    def test_returns_true_when_the_directory_holds_importable_files(self) -> None:
        client = FakeClient({"/data": [FakeAttributes("orders.csv")]})

        with _patched_connection(client):
            assert validate_credentials(host="h", port=22, user="u", auth=SFTPAuth(password="p"), path="/data") is True

    @pytest.mark.parametrize(
        ("entries", "file_pattern"),
        [
            ([], None),
            ([FakeAttributes("readme.md")], None),
            ([FakeAttributes("orders.csv")], r"\.json$"),
        ],
    )
    def test_rejects_a_folder_with_nothing_to_import(
        self, entries: list[FakeAttributes], file_pattern: str | None
    ) -> None:
        client = FakeClient({"/data": entries})

        with _patched_connection(client):
            with pytest.raises(SFTPCredentialsError, match=NO_MATCHING_FILES_ERROR):
                validate_credentials(
                    host="h", port=22, user="u", auth=SFTPAuth(password="p"), path="/data", file_pattern=file_pattern
                )

    def test_an_explicit_format_accepts_files_without_a_known_extension(self) -> None:
        client = FakeClient({"/data": [FakeAttributes("export")]})

        with _patched_connection(client):
            assert (
                validate_credentials(
                    host="h", port=22, user="u", auth=SFTPAuth(password="p"), path="/data", configured_format="csv"
                )
                is True
            )

    def test_rejects_an_invalid_pattern_before_connecting(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp.sftp_connection"
        ) as connection:
            with pytest.raises(SFTPCredentialsError, match=PATTERN_ERROR):
                validate_credentials(
                    host="h", port=22, user="u", auth=SFTPAuth(password="p"), path="/data", file_pattern="(["
                )

        connection.assert_not_called()

    def test_rejects_an_invalid_delimiter_before_connecting(self) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.sftp.sftp.sftp_connection"
        ) as connection:
            with pytest.raises(SFTPCredentialsError, match=DELIMITER_ERROR):
                validate_credentials(
                    host="h", port=22, user="u", auth=SFTPAuth(password="p"), path="/data", delimiter="||"
                )

        connection.assert_not_called()

    def test_surfaces_an_unreadable_directory(self) -> None:
        client = FakeClient({"/data": []}, unreadable={"/data"})

        with _patched_connection(client):
            with pytest.raises(SFTPCredentialsError, match=DIRECTORY_ERROR):
                validate_credentials(host="h", port=22, user="u", auth=SFTPAuth(password="p"), path="/data")


class TestSFTPSource:
    def test_response_shape_and_lazy_items(self) -> None:
        client = FakeClient(
            {"/data": [FakeAttributes("orders.csv")]},
            contents={"/data/orders.csv": b"id\n1\n"},
        )

        response = sftp_source(
            host="h", port=22, user="u", schema_name="orders", auth=SFTPAuth(password="p"), path="/data"
        )

        assert response.name == "orders"
        assert response.primary_keys is None

        with _patched_connection(client):
            rows = [row for chunk in cast(Any, response.items()) for row in chunk]

        assert [row["id"] for row in rows] == ["1"]
