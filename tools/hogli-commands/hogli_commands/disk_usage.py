from __future__ import annotations

import os
import sys
import stat
import ctypes
import struct
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, kw_only=True, slots=True)
class DiskUsage:
    freeable_bytes: int
    allocated_bytes: int

    def __add__(self, other: DiskUsage) -> DiskUsage:
        return DiskUsage(
            freeable_bytes=self.freeable_bytes + other.freeable_bytes,
            allocated_bytes=self.allocated_bytes + other.allocated_bytes,
        )


NO_USAGE = DiskUsage(freeable_bytes=0, allocated_bytes=0)


@dataclass(frozen=True, kw_only=True, slots=True)
class _FileBlocks:
    inode: int
    link_count: int
    allocated_bytes: int
    unshared_bytes: int


def measure_disk_usage(paths: Sequence[Path]) -> DiskUsage:
    """What deleting *paths* would free, next to what they occupy.

    A file whose blocks are shared frees nothing while the other owner keeps
    them. pnpm and uv clone each file from their store on APFS and hard-link
    it on other file systems, so `du` reports a dependency folder as many
    times larger than its deletion frees. A hard-linked file counts as
    freeable only when every one of its links is inside *paths*. Symlinks and
    other mounted file systems are not followed.
    """

    # One int per hard-linked inode, because pnpm hard-links every file in a large tree on Linux.
    links_not_seen: dict[tuple[int, int], int] = {}
    freeable = allocated = 0
    for path in paths:
        for device, blocks in _walk_files(path):
            if blocks.link_count <= 1:
                allocated += blocks.allocated_bytes
                freeable += blocks.unshared_bytes
                continue
            key = (device, blocks.inode)
            remaining = links_not_seen.get(key)
            if remaining is None:
                allocated += blocks.allocated_bytes
                remaining = blocks.link_count
            remaining -= 1
            if remaining == 0:
                links_not_seen.pop(key, None)
                freeable += blocks.unshared_bytes
            else:
                links_not_seen[key] = remaining
    return DiskUsage(freeable_bytes=freeable, allocated_bytes=allocated)


def _walk_files(path: Path) -> Iterator[tuple[int, _FileBlocks]]:
    try:
        device = path.lstat().st_dev
        if path.is_symlink() or not path.is_dir():
            if path.is_file() and (blocks := _file_blocks(str(path))) is not None:
                yield device, blocks
            return
    except OSError:
        return
    pending = [str(path)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        # Another file system mounted inside frees nothing here, and a stale network mount can block the walk.
                        if entry.stat(follow_symlinks=False).st_dev == device:
                            pending.append(entry.path)
                    elif entry.is_file(follow_symlinks=False) and (blocks := _file_blocks(entry.path)) is not None:
                        yield device, blocks
        except OSError:
            continue


def _blocks_from_lstat(path: str) -> _FileBlocks | None:
    try:
        status = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(status.st_mode):
        return None
    allocated = status.st_blocks * 512
    return _FileBlocks(
        inode=status.st_ino, link_count=status.st_nlink, allocated_bytes=allocated, unshared_bytes=allocated
    )


def _apfs_blocks_reader() -> Callable[[str], _FileBlocks | None]:
    """Read a file's blocks with getattrlist(2), whose ATTR_CMNEXT_PRIVATESIZE excludes the blocks that APFS clones share."""

    libc = ctypes.CDLL(None, use_errno=True)
    getattrlist = libc.getattrlist
    getattrlist.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
    getattrlist.restype = ctypes.c_int

    class AttrList(ctypes.Structure):
        _fields_ = [
            ("bitmapcount", ctypes.c_ushort),
            ("reserved", ctypes.c_uint16),
            ("commonattr", ctypes.c_uint32),
            ("volattr", ctypes.c_uint32),
            ("dirattr", ctypes.c_uint32),
            ("fileattr", ctypes.c_uint32),
            ("forkattr", ctypes.c_uint32),
        ]

    attr_cmn_fileid, attr_file_linkcount, attr_file_allocsize, attr_cmnext_privatesize = 0x02000000, 0x1, 0x4, 0x8
    fsopt_nofollow, fsopt_attr_cmn_extended = 0x1, 0x20
    request = AttrList(5, 0, attr_cmn_fileid, 0, 0, attr_file_linkcount | attr_file_allocsize, attr_cmnext_privatesize)
    options = fsopt_nofollow | fsopt_attr_cmn_extended
    # The kernel packs the requested attributes after a u32 length, in group order and then bit order within a group.
    layout = struct.Struct("<IQIqq")

    def read(path: str) -> _FileBlocks | None:
        buffer = ctypes.create_string_buffer(layout.size)
        if getattrlist(os.fsencode(path), ctypes.byref(request), buffer, layout.size, options) != 0:
            return _blocks_from_lstat(path)
        returned_length, inode, link_count, allocated, unshared = layout.unpack(buffer.raw)
        if returned_length != layout.size:
            return _blocks_from_lstat(path)
        return _FileBlocks(inode=inode, link_count=link_count, allocated_bytes=allocated, unshared_bytes=unshared)

    return read


_file_blocks: Callable[[str], _FileBlocks | None] = (
    _apfs_blocks_reader() if sys.platform == "darwin" else _blocks_from_lstat
)
