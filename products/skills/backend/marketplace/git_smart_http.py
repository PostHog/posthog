"""Minimal read-only Git Smart HTTP v2 server for serving a synthesized marketplace repo.

Synthesizes a virtual git repository from a file tree (``path -> content``) and
implements just enough of the Git Smart HTTP protocol for ``git clone`` (and therefore
Claude Code's ``/plugin marketplace add``). There is no repo on disk, no push support,
and no delta compression.

This module is deliberately framework-agnostic and stdlib-only — it imports no Django.
That keeps the packfile synthesis unit-testable against the real ``git`` binary without
booting the app, and lets the DRF view (and a throwaway stdlib server) share one code path.

Ported from the reference implementation in daniloc/mnemion (``src/git.ts``).
"""

import zlib
import hashlib
from dataclasses import dataclass

OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3


class GitSynthesisError(Exception):
    """Raised when a file tree would produce a corrupt git object (empty or duplicate
    tree-entry name, or a path used as both a file and a directory)."""


# Fixed author/committer timestamp so identical content always hashes to the same
# commit SHA — that determinism is what lets Claude Code decide "nothing changed".
_FIXED_TIMESTAMP = "1700000000 +0000"

FileTree = dict[str, str]


@dataclass(frozen=True)
class GitObject:
    type: int
    data: bytes
    sha: str


@dataclass(frozen=True)
class SynthesizedRepo:
    objects: list[GitObject]
    head_sha: str
    # The finished (zlib-compressed) packfile, computed once at synthesis. Carried on the repo so
    # the team+version cache memoizes it — otherwise every clone / auto-update poll would recompress
    # the whole corpus (the dominant CPU cost), which the cache otherwise wouldn't avoid.
    packfile: bytes


def _git_hash(obj_type: str, data: bytes) -> str:
    header = f"{obj_type} {len(data)}\0".encode()
    # SHA1 is the git object-ID hash mandated by the wire protocol, not a security primitive.
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()  # nosemgrep


def _create_blob(content: str) -> GitObject:
    data = content.encode()
    return GitObject(type=OBJ_BLOB, data=data, sha=_git_hash("blob", data))


@dataclass(frozen=True)
class _TreeEntry:
    mode: str
    name: str
    sha: str


def _create_tree(entries: list[_TreeEntry]) -> GitObject:
    # Git sorts tree entries by name, treating directories as if they had a trailing slash.
    def sort_key(entry: _TreeEntry) -> str:
        return entry.name + "/" if entry.mode.startswith("40") else entry.name

    parts = bytearray()
    for entry in sorted(entries, key=sort_key):
        parts += f"{entry.mode} {entry.name}\0".encode()
        parts += bytes.fromhex(entry.sha)
    data = bytes(parts)
    return GitObject(type=OBJ_TREE, data=data, sha=_git_hash("tree", data))


def _create_commit(tree_sha: str, message: str, author: str) -> GitObject:
    email = f"{author.lower()}@localhost"
    text = (
        f"tree {tree_sha}\n"
        f"author {author} <{email}> {_FIXED_TIMESTAMP}\n"
        f"committer {author} <{email}> {_FIXED_TIMESTAMP}\n"
        f"\n{message}\n"
    )
    data = text.encode()
    return GitObject(type=OBJ_COMMIT, data=data, sha=_git_hash("commit", data))


@dataclass
class _DirNode:
    files: dict[str, str]  # filename -> blob sha
    dirs: dict[str, "_DirNode"]


def _reject_bad_tree_entry(name: str, seen: set[str]) -> None:
    if not name:
        raise GitSynthesisError("empty tree-entry name (a file path is empty or ends in '/')")
    # Case-insensitive: two entries differing only by case pass git fsck but abort `git clone`
    # on a case-insensitive filesystem (macOS/Windows) — break the whole team's clone.
    key = name.lower()
    if key in seen:
        raise GitSynthesisError(
            f"tree-entry name collides (case-insensitively) or is used as both file and dir: {name!r}"
        )
    seen.add(key)


def synthesize_repo(files: FileTree, *, author: str, message: str) -> SynthesizedRepo:
    """Turn a ``path -> content`` map into the git objects of a single-commit repo."""
    objects: list[GitObject] = []
    blob_shas: dict[str, str] = {}

    for path, content in files.items():
        blob = _create_blob(content)
        objects.append(blob)
        blob_shas[path] = blob.sha

    root = _DirNode(files={}, dirs={})
    for path in files:
        parts = path.split("/")
        filename = parts.pop()
        node = root
        for directory in parts:
            node = node.dirs.setdefault(directory, _DirNode(files={}, dirs={}))
        node.files[filename] = blob_shas[path]

    def build_tree(node: _DirNode) -> str:
        # Reject anything that would emit an invalid tree (empty name) or a tree with two
        # entries of the same name (a path used as both a file and a directory) — real git
        # refuses to unpack such a pack, which would break the clone for the whole team.
        seen: set[str] = set()
        entries: list[_TreeEntry] = []
        for name, sha in node.files.items():
            _reject_bad_tree_entry(name, seen)
            entries.append(_TreeEntry(mode="100644", name=name, sha=sha))
        for name, child in node.dirs.items():
            _reject_bad_tree_entry(name, seen)
            entries.append(_TreeEntry(mode="40000", name=name, sha=build_tree(child)))
        tree = _create_tree(entries)
        objects.append(tree)
        return tree.sha

    root_sha = build_tree(root)
    commit = _create_commit(root_sha, message=message, author=author)
    objects.append(commit)
    return SynthesizedRepo(objects=objects, head_sha=commit.sha, packfile=build_packfile(objects))


def _encode_obj_header(obj_type: int, size: int) -> bytes:
    out = bytearray()
    b = (obj_type << 4) | (size & 0x0F)
    size >>= 4
    if size > 0:
        b |= 0x80
    out.append(b)
    while size > 0:
        b = size & 0x7F
        size >>= 7
        if size > 0:
            b |= 0x80
        out.append(b)
    return bytes(out)


def build_packfile(objects: list[GitObject]) -> bytes:
    body = bytearray()
    body += b"PACK"
    body += (2).to_bytes(4, "big")
    body += len(objects).to_bytes(4, "big")
    for obj in objects:
        body += _encode_obj_header(obj.type, len(obj.data))
        body += zlib.compress(obj.data)
    # Packfile trailer is a SHA1 checksum over the pack contents, fixed by the git pack format.
    body += hashlib.sha1(bytes(body), usedforsecurity=False).digest()  # nosemgrep
    return bytes(body)


def _pkt_line(data: str) -> bytes:
    payload = data.encode()
    return f"{len(payload) + 4:04x}".encode() + payload


_FLUSH_PKT = b"0000"


def _side_band_chunks(band: int, data: bytes) -> bytes:
    # side-band-64k frames cap the payload at 65520 minus 4 (length) and 1 (band byte).
    max_chunk = 65515
    out = bytearray()
    for offset in range(0, len(data), max_chunk):
        slice_ = data[offset : offset + max_chunk]
        length = len(slice_) + 5
        out += f"{length:04x}".encode()
        out.append(band)
        out += slice_
    return bytes(out)


INFO_REFS_CONTENT_TYPE = "application/x-git-upload-pack-advertisement"
UPLOAD_PACK_CONTENT_TYPE = "application/x-git-upload-pack-result"


def build_info_refs(head_sha: str) -> bytes:
    """Body for ``GET /info/refs?service=git-upload-pack`` (the ref advertisement)."""
    caps = "side-band-64k shallow symref=HEAD:refs/heads/main"
    out = bytearray()
    out += _pkt_line("# service=git-upload-pack\n")
    out += _FLUSH_PKT
    out += _pkt_line(f"{head_sha} HEAD\0{caps}\n")
    out += _pkt_line(f"{head_sha} refs/heads/main\n")
    out += _FLUSH_PKT
    return bytes(out)


def _parse_pkt_lines(body: bytes) -> list[bytes]:
    """Split a Git pkt-line stream into its payloads (flush-pkts skipped). Stops at the
    first malformed length rather than scanning raw bytes — so command detection matches
    actual pkt-line commands, not substrings that merely appear in a ref name."""
    lines: list[bytes] = []
    offset = 0
    total = len(body)
    while offset + 4 <= total:
        try:
            length = int(body[offset : offset + 4], 16)
        except ValueError:
            break
        if length == 0:  # flush-pkt
            offset += 4
            continue
        if length < 4 or offset + length > total:
            break
        lines.append(body[offset + 4 : offset + length])
        offset += length
    return lines


def build_upload_pack(request_body: bytes, repo: SynthesizedRepo) -> bytes:
    """Body for ``POST /git-upload-pack`` (negotiation result + packfile)."""
    commands = _parse_pkt_lines(request_body)
    is_shallow = any(line.startswith(b"deepen") for line in commands)
    is_done = any(line.rstrip(b"\n") == b"done" for line in commands)

    out = bytearray()
    if is_shallow:
        out += _pkt_line(f"shallow {repo.head_sha}\n")
        out += _FLUSH_PKT
    if is_done:
        out += _pkt_line("NAK\n")
        out += _side_band_chunks(1, repo.packfile)  # precomputed at synthesis (cached), not recompressed here
        out += _FLUSH_PKT
    return bytes(out)
