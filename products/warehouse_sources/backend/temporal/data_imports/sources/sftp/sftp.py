import io
import re
import csv
import gzip
import json
import stat
import socket
import posixpath
import dataclasses
from collections.abc import Generator, Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from io import StringIO
from typing import IO, Any, Protocol, cast

import re2
import paramiko
from structlog.types import FilteringBoundLogger

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.models.ssh_tunnel import from_private_key
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sftp.settings import (
    CHUNK_SIZE,
    CONNECT_TIMEOUT_SECONDS,
    DEFAULT_DELIMITER,
    EXTENSION_DELIMITERS,
    EXTENSION_FORMATS,
    FILE_MODIFIED_AT_COLUMN,
    FILE_PATH_COLUMN,
    MAX_DIRECTORIES,
    MAX_DIRECTORY_DEPTH,
    MAX_FILES,
    MAX_JSON_DOCUMENT_BYTES,
    MAX_PREFETCH_BYTES,
    READ_TIMEOUT_SECONDS,
    ConfiguredFileFormat,
    FileFormat,
)

# Error message prefixes. `get_non_retryable_errors` matches on these, so they have to stay stable
# and stay out of the interpolated part of each message.
AUTH_FAILED_ERROR = "SFTP authentication failed"
CONNECTION_FAILED_ERROR = "Couldn't connect to the SFTP server"
PRIVATE_KEY_ERROR = "The SSH private key could not be read"
DIRECTORY_ERROR = "Couldn't read the remote directory"
PATTERN_ERROR = "The file pattern isn't a valid regular expression"
NO_FILES_ERROR = "No remote files are available for table"
NO_MATCHING_FILES_ERROR = "No importable files were found"
FORMAT_ERROR = "Can't work out the format of the remote file"
DELIMITER_ERROR = "The CSV delimiter must be a single character"


class SFTPCredentialsError(Exception):
    """A permanent configuration problem: unreachable host, rejected credentials, missing directory."""


class SFTPFileFormatError(Exception):
    """A remote file couldn't be parsed with the configured (or inferred) format."""


class RemoteAttributes(Protocol):
    filename: str
    st_mode: int | None
    st_size: int | None
    st_mtime: float | int | None


class RemoteClient(Protocol):
    """The slice of `paramiko.SFTPClient` this source uses."""

    def listdir_attr(self, path: str) -> list[Any]: ...

    def open(self, filename: str, mode: str = "r", bufsize: int = -1) -> Any: ...


@dataclasses.dataclass(frozen=True)
class RemoteFile:
    path: str
    relative_path: str
    size: int
    modified_at: datetime


@dataclasses.dataclass(frozen=True)
class ResolvedFormat:
    file_format: FileFormat
    delimiter: str
    compressed: bool


def normalize_remote_path(path: str | None) -> str:
    stripped = (path or "").strip()
    if not stripped:
        return "."
    normalized = posixpath.normpath(stripped)
    return normalized.rstrip("/") or "/"


def normalize_delimiter(delimiter: str | None) -> str | None:
    """Accept a literal tab, an escaped `\\t`, or the word `tab` for tab-separated files."""
    if delimiter is None:
        return None
    if delimiter in ("\\t", "tab", "\t"):
        return "\t"
    if delimiter == "":
        return None
    if len(delimiter) != 1:
        raise SFTPCredentialsError(f"{DELIMITER_ERROR} (got {delimiter!r}). Use \\t for tab-separated files.")
    return delimiter


def load_private_key(private_key: str, passphrase: str | None = None) -> paramiko.PKey:
    try:
        return from_private_key(StringIO(private_key), passphrase or None)
    except Exception as e:
        raise SFTPCredentialsError(
            f"{PRIVATE_KEY_ERROR}. Paste the full private key including the -----BEGIN and -----END lines, "
            "and check the passphrase if the key is encrypted."
        ) from e


@frozen
class SFTPAuth:
    """How to authenticate as the configured user: a password, or an SSH key with optional passphrase."""

    password: str | None = dataclasses.field(default=None, repr=False)
    private_key: str | None = dataclasses.field(default=None, repr=False)
    passphrase: str | None = dataclasses.field(default=None, repr=False)

    def pkey(self) -> paramiko.PKey | None:
        return load_private_key(self.private_key, self.passphrase) if self.private_key else None


@contextmanager
def sftp_connection(
    host: str,
    port: int,
    user: str,
    auth: SFTPAuth,
    timeout: int = CONNECT_TIMEOUT_SECONDS,
) -> Generator[paramiko.SFTPClient]:
    pkey = auth.pkey()

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as e:
        raise SFTPCredentialsError(
            f"{CONNECTION_FAILED_ERROR} at {host}:{port}. Check the host and port, and that the server "
            "accepts connections from the public internet."
        ) from e

    # The connect timeout must not linger as a read timeout — a large file transfer can idle
    # longer than the handshake ever should.
    sock.settimeout(None)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = timeout

    try:
        try:
            transport.connect(username=user, password=auth.password or None, pkey=pkey)
        except paramiko.AuthenticationException as e:
            raise SFTPCredentialsError(
                f"{AUTH_FAILED_ERROR} for user '{user}'. Check the username and password or SSH key."
            ) from e
        except (paramiko.SSHException, OSError) as e:
            raise SFTPCredentialsError(f"{CONNECTION_FAILED_ERROR} at {host}:{port}: {e}") from e

        client = paramiko.SFTPClient.from_transport(transport)
        if client is None:
            raise SFTPCredentialsError(
                f"{CONNECTION_FAILED_ERROR} at {host}:{port}: the server didn't open an SFTP session. "
                "Check that the SFTP subsystem is enabled for this user."
            )

        # Bound directory and file reads so a server that connects and then stalls can't hold an
        # iterator thread indefinitely. The handshake is already bounded by `banner_timeout`.
        channel = client.get_channel()
        if channel is not None:
            channel.settimeout(READ_TIMEOUT_SECONDS)

        try:
            yield client
        finally:
            client.close()
    finally:
        transport.close()


def _to_datetime(mtime: float | int | None) -> datetime:
    return datetime.fromtimestamp(mtime or 0, tz=UTC)


class CompiledPattern(Protocol):
    def search(self, string: str) -> object | None: ...


def _compile_pattern(pattern: str | None) -> CompiledPattern | None:
    if not pattern:
        return None
    # re2 is linear-time, so a user-supplied pattern can't pin a worker CPU by backtracking on a
    # long filename (matching runs during discovery and every sync, before the file-count limit).
    try:
        return cast(CompiledPattern, re2.compile(pattern))
    except re2.error as e:
        raise SFTPCredentialsError(f"{PATTERN_ERROR}: {e}") from e


def list_remote_files(
    client: RemoteClient,
    root: str,
    pattern: str | None = None,
    max_depth: int = MAX_DIRECTORY_DEPTH,
    max_files: int = MAX_FILES,
    max_directories: int = MAX_DIRECTORIES,
    logger: FilteringBoundLogger | None = None,
) -> list[RemoteFile]:
    """List regular files under `root`, breadth-first, filtered by `pattern` on the relative path."""
    compiled = _compile_pattern(pattern)
    root = normalize_remote_path(root)

    files: list[RemoteFile] = []
    queue: list[tuple[str, int]] = [(root, 0)]
    queued_directories = 1
    skipped_directories = False

    while queue:
        directory, depth = queue.pop(0)
        try:
            entries = cast(list[RemoteAttributes], client.listdir_attr(directory))
        except OSError as e:
            if directory == root:
                raise SFTPCredentialsError(
                    f"{DIRECTORY_ERROR} '{directory}'. Check that it exists and that the user can read it."
                ) from e
            if logger is not None:
                logger.warning("Skipping unreadable SFTP directory", directory=directory, error=str(e))
            continue

        for entry in sorted(entries, key=lambda e: e.filename):
            if entry.filename in (".", ".."):
                continue
            full_path = posixpath.join(directory, entry.filename)
            mode = entry.st_mode or 0
            if stat.S_ISDIR(mode):
                if depth < max_depth:
                    if queued_directories >= max_directories:
                        skipped_directories = True
                        continue
                    queue.append((full_path, depth + 1))
                    queued_directories += 1
                continue
            # Anything that isn't a plain file (symlinks, sockets, devices) is skipped: following
            # links risks cycles, and only regular files can be parsed.
            if not stat.S_ISREG(mode):
                continue

            relative_path = posixpath.relpath(full_path, root)
            if compiled is not None and not compiled.search(relative_path):
                continue

            files.append(
                RemoteFile(
                    path=full_path,
                    relative_path=relative_path,
                    size=entry.st_size or 0,
                    modified_at=_to_datetime(entry.st_mtime),
                )
            )

            if len(files) >= max_files:
                if logger is not None:
                    logger.warning(
                        "Reached the SFTP file limit; later files are ignored",
                        root=root,
                        max_files=max_files,
                    )
                return sorted(files, key=lambda f: f.relative_path)

    if skipped_directories and logger is not None:
        logger.warning(
            "Reached the SFTP folder limit; later folders are ignored",
            root=root,
            max_directories=max_directories,
        )

    return sorted(files, key=lambda f: f.relative_path)


def sanitize_table_name(name: str) -> str:
    sanitized = re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_").lower()
    return sanitized or "sftp_data"


def table_name_for_file(relative_path: str) -> str:
    without_compression = re.sub(r"\.gz$", "", relative_path, flags=re.IGNORECASE)
    stem = posixpath.splitext(without_compression)[0]
    return sanitize_table_name(stem)


def group_files_by_table(
    files: Iterable[RemoteFile], combined_table_name: str | None = None
) -> dict[str, list[RemoteFile]]:
    """Map table name -> the files feeding it.

    One table per file by default; a single combined table when the user opted into that. Names are
    derived from the (sorted) relative paths, so the same remote tree always produces the same tables.
    """
    ordered = sorted(files, key=lambda f: f.relative_path)

    if combined_table_name:
        return {sanitize_table_name(combined_table_name): ordered}

    grouped: dict[str, list[RemoteFile]] = {}
    for file in ordered:
        base = table_name_for_file(file.relative_path)
        name = base
        suffix = 2
        while name in grouped:
            name = f"{base}_{suffix}"
            suffix += 1
        grouped[name] = [file]
    return grouped


def is_format_inferable(relative_path: str) -> bool:
    lowered = relative_path.lower()
    if lowered.endswith(".gz"):
        lowered = lowered[: -len(".gz")]
    return posixpath.splitext(lowered)[1] in EXTENSION_FORMATS


def parseable_files(
    files: Iterable[RemoteFile], configured_format: ConfiguredFileFormat | str | None = "infer"
) -> list[RemoteFile]:
    """Drop files whose format can't be worked out, so discovery never offers a table that can't sync.

    An explicit file format applies to every matched file, so nothing is dropped then. Both discovery
    and the sync filter identically — otherwise the same remote tree would produce different table names.
    """
    if configured_format and configured_format != "infer":
        return list(files)
    return [file for file in files if is_format_inferable(file.relative_path)]


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
            raise SFTPFileFormatError(
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


def _dedupe_headers(headers: list[str]) -> list[str]:
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
            headers = _dedupe_headers(row)
            continue
        if not any(cell.strip() for cell in row):
            continue
        if len(row) > len(headers):
            # More values than headers means the file is malformed or the delimiter is wrong.
            # Dropping the row keeps the extra values from silently landing in the wrong columns.
            if logger is not None:
                logger.warning(
                    "Skipping SFTP CSV row with more values than headers",
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
            raise SFTPFileFormatError(
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
        raise SFTPFileFormatError(
            f"'{relative_path}' is larger than the {MAX_JSON_DOCUMENT_BYTES // (1024 * 1024)} MB limit for a "
            "single JSON document. Convert it to JSON Lines (one object per line) so it can stream in."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SFTPFileFormatError(
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


def iter_table_rows(
    client: RemoteClient,
    files: Iterable[RemoteFile],
    configured_format: ConfiguredFileFormat | str | None = "infer",
    delimiter: str | None = None,
    chunk_size: int = CHUNK_SIZE,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[list[dict[str, Any]]]:
    for file in files:
        resolved = resolve_file_format(file.relative_path, configured_format, delimiter)
        with client.open(file.path, "rb") as handle:
            prefetch = getattr(handle, "prefetch", None)
            if callable(prefetch) and file.size:
                # Cap what we ask paramiko to prefetch so a server that reports a huge size can't
                # blow up the prefetch descriptor list; bytes past the cap are read on demand.
                prefetch(min(file.size, MAX_PREFETCH_BYTES))
            for chunk in iter_file_rows(handle, resolved, file.relative_path, chunk_size, logger):
                yield [
                    {
                        **row,
                        FILE_PATH_COLUMN: file.relative_path,
                        FILE_MODIFIED_AT_COLUMN: file.modified_at,
                    }
                    for row in chunk
                ]


def get_rows(
    host: str,
    port: int,
    user: str,
    schema_name: str,
    auth: SFTPAuth,
    path: str = "/",
    file_pattern: str | None = None,
    configured_format: ConfiguredFileFormat | str | None = "infer",
    delimiter: str | None = None,
    combined_table_name: str | None = None,
    logger: FilteringBoundLogger | None = None,
) -> Iterator[list[dict[str, Any]]]:
    with sftp_connection(host=host, port=port, user=user, auth=auth) as client:
        files = parseable_files(list_remote_files(client, path, file_pattern, logger=logger), configured_format)
        grouped = group_files_by_table(files, combined_table_name)
        target = grouped.get(schema_name)
        if not target:
            raise SFTPCredentialsError(
                f"{NO_FILES_ERROR} '{schema_name}'. The file it was discovered from may have been renamed, "
                "moved, or removed on the SFTP server."
            )
        yield from iter_table_rows(client, target, configured_format, delimiter, logger=logger)


def validate_credentials(
    host: str,
    port: int,
    user: str,
    auth: SFTPAuth,
    path: str = "/",
    file_pattern: str | None = None,
    configured_format: ConfiguredFileFormat | str | None = "infer",
    delimiter: str | None = None,
) -> bool:
    """Connect, then confirm the folder holds at least one importable file.

    Raises `SFTPCredentialsError` for anything the user has to fix. The file check mirrors discovery:
    a folder with nothing importable would create a source with no tables, which is a dead end.
    """
    _compile_pattern(file_pattern)
    # Catch a bad delimiter here rather than on every sync — it's a permanent misconfiguration.
    normalize_delimiter(delimiter)
    with sftp_connection(host=host, port=port, user=user, auth=auth) as client:
        files = parseable_files(list_remote_files(client, path, file_pattern), configured_format)

    if not files:
        raise SFTPCredentialsError(
            f"{NO_MATCHING_FILES_ERROR} in '{normalize_remote_path(path)}'. PostHog connected to the server "
            "but found nothing to import there. Check the folder, the file pattern, and the file format."
        )

    return True


def sftp_source(
    host: str,
    port: int,
    user: str,
    schema_name: str,
    auth: SFTPAuth,
    path: str = "/",
    file_pattern: str | None = None,
    configured_format: ConfiguredFileFormat | str | None = "infer",
    delimiter: str | None = None,
    combined_table_name: str | None = None,
    logger: FilteringBoundLogger | None = None,
) -> SourceResponse:
    return SourceResponse(
        name=schema_name,
        items=lambda: get_rows(
            host=host,
            port=port,
            user=user,
            schema_name=schema_name,
            auth=auth,
            path=path,
            file_pattern=file_pattern,
            configured_format=configured_format,
            delimiter=delimiter,
            combined_table_name=combined_table_name,
            logger=logger,
        ),
        # Files carry no stable row identity, so tables are replaced wholesale on every sync.
        primary_keys=None,
    )
