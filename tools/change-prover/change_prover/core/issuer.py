"""The issuer manifest: the one list of default-branch paths the dependency proof runs from.

The prover pins every listed path in its marker, and stamphog reads the same file from the default
branch and ignores a proof that does not pin each path. A path that ends in `/` is a directory and
is pinned by its git tree id, so a file added under it changes the pin too. Any other path is a
file, pinned by its blob id.
"""

from __future__ import annotations

import re

from change_prover.core.lockfile_yaml import load_yaml
from change_prover.core.policy import Refused

MANIFEST_PATH = "tools/change-prover/issuer.yml"
MAX_BYTES = 16 * 1024
MAX_PATHS = 32
GLOB_CHARACTERS = re.compile(r"[*?\[\]{}\\]")


class InvalidIssuerManifest(Exception):
    """The manifest cannot say what the publisher is, so no proof can be made."""


def is_directory(path: str) -> bool:
    return path.endswith("/")


def covers(entry: str, path: str) -> bool:
    return entry == path or (is_directory(entry) and path.startswith(entry))


def _check_path(path: object) -> str:
    if not isinstance(path, str) or not path:
        raise InvalidIssuerManifest(f"{path!r} is not a non-empty string")
    if GLOB_CHARACTERS.search(path):
        raise InvalidIssuerManifest(f"{path} uses a glob character")
    segments = path.removesuffix("/").split("/")
    # A leading `/` and a doubled `/` both leave an empty segment.
    if any(segment in ("", ".", "..") for segment in segments):
        raise InvalidIssuerManifest(f"{path} is not a plain repo-relative path")
    return path


def parse_manifest(text: bytes, own_path: str) -> tuple[str, ...]:
    """The manifest's paths, refused unless the manifest is well formed and lists itself."""
    if len(text) > MAX_BYTES:
        raise InvalidIssuerManifest(f"{own_path} is larger than {MAX_BYTES} bytes")
    try:
        loaded = load_yaml(text)
    except Refused as error:
        raise InvalidIssuerManifest(f"{own_path} does not parse: {error}") from error
    if set(loaded) != {"paths"}:
        raise InvalidIssuerManifest(f"{own_path} must hold the single key `paths`")
    raw = loaded["paths"]
    if not isinstance(raw, list) or not raw:
        raise InvalidIssuerManifest(f"{own_path}: `paths` must be a non-empty list")
    if len(raw) > MAX_PATHS:
        raise InvalidIssuerManifest(f"{own_path} lists more than {MAX_PATHS} paths")
    paths = tuple(_check_path(path) for path in raw)
    if len(set(paths)) != len(paths):
        raise InvalidIssuerManifest(f"{own_path} lists a path twice")
    # The manifest decides what is pinned, so an edit to it must change a pin as well.
    if not any(covers(entry, own_path) for entry in paths):
        raise InvalidIssuerManifest(f"{own_path} does not cover itself")
    return paths
