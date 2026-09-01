from typing import Literal

FileFormat = Literal["csv", "jsonl", "json"]
ConfiguredFileFormat = Literal["infer", "csv", "jsonl", "json"]

DEFAULT_PORT = 22
CONNECT_TIMEOUT_SECONDS = 30
# Per-operation read timeout for directory and file transfers. A responsive server keeps data
# flowing well within this, so it only trips on a stalled server holding an iterator thread.
READ_TIMEOUT_SECONDS = 300

# A whole-document JSON file has to be materialized to parse it, so cap how many decompressed bytes
# we read before giving up and steering the user to JSON Lines (which streams). Also stops a small
# gzip file from decompressing into unbounded memory.
MAX_JSON_DOCUMENT_BYTES = 256 * 1024 * 1024

# Paramiko builds one prefetch descriptor per 32 KiB block up to the requested size, so a server that
# reports an enormous file size could balloon that list. Cap it: bytes past this are read on demand.
MAX_PREFETCH_BYTES = 256 * 1024 * 1024

# A remote tree is walked breadth-first with all three bounds enforced: an SFTP server can expose an
# arbitrarily deep/wide tree, and discovery has to terminate without the user configuring limits.
MAX_DIRECTORY_DEPTH = 5
MAX_FILES = 1000
# Depth and file count alone don't bound the walk: `MAX_FILES` counts only files matching the
# pattern, so a pattern matching nothing (or a tree of nothing but folders) leaves the breadth of
# each level unbounded. Capping how many folders are ever queued bounds both the listing round trips
# and the queue itself.
MAX_DIRECTORIES = 1000

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
