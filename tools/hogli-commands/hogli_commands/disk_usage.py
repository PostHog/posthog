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
            for blocks in _read_directory(directory, device, pending):
                yield device, blocks
        except OSError:
            continue


def _scandir_directory(directory: str, device: int, subdirectories: list[str]) -> Iterator[_FileBlocks]:
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                # Another file system mounted inside frees nothing here, and a stale network mount can block the walk.
                if entry.stat(follow_symlinks=False).st_dev == device:
                    subdirectories.append(entry.path)
            elif entry.is_file(follow_symlinks=False) and (blocks := _file_blocks(entry.path)) is not None:
                yield blocks


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


class _AttrList(ctypes.Structure):
    _fields_ = [
        ("bitmapcount", ctypes.c_ushort),
        ("reserved", ctypes.c_uint16),
        ("commonattr", ctypes.c_uint32),
        ("volattr", ctypes.c_uint32),
        ("dirattr", ctypes.c_uint32),
        ("fileattr", ctypes.c_uint32),
        ("forkattr", ctypes.c_uint32),
    ]


_ATTR_CMN_NAME = 0x1
_ATTR_CMN_OBJTYPE = 0x8
_ATTR_CMN_FILEID = 0x02000000
_ATTR_CMN_ERROR = 0x20000000
_ATTR_CMN_RETURNED_ATTRS = 0x80000000
_ATTR_DIR_MOUNTSTATUS = 0x4
_DIR_MNTSTATUS_MNTPOINT = 0x1
_DIR_MNTSTATUS_TRIGGER = 0x2
_ATTR_FILE_LINKCOUNT = 0x1
_ATTR_FILE_ALLOCSIZE = 0x4
_ATTR_CMNEXT_PRIVATESIZE = 0x8
_FSOPT_NOFOLLOW = 0x1
_FSOPT_ATTR_CMN_EXTENDED = 0x20
_VREG = 1
_VDIR = 2

_U32 = struct.Struct("<I")
_U64 = struct.Struct("<Q")
_OFF_T = struct.Struct("<q")
_ATTRIBUTE_REFERENCE = struct.Struct("<iI")
_BULK_ENTRY_HEADER = struct.Struct("<I5I")
_BULK_BUFFER_BYTES = 64 * 1024


def _apfs_blocks_reader() -> Callable[[str], _FileBlocks | None]:
    """Read a file's blocks with getattrlist(2), whose ATTR_CMNEXT_PRIVATESIZE excludes the blocks that APFS clones share."""

    libc = ctypes.CDLL(None, use_errno=True)
    getattrlist = libc.getattrlist
    getattrlist.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
    getattrlist.restype = ctypes.c_int

    request = _AttrList(
        5, 0, _ATTR_CMN_FILEID, 0, 0, _ATTR_FILE_LINKCOUNT | _ATTR_FILE_ALLOCSIZE, _ATTR_CMNEXT_PRIVATESIZE
    )
    options = _FSOPT_NOFOLLOW | _FSOPT_ATTR_CMN_EXTENDED
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


def _bulk_directory_reader() -> Callable[[str, int, list[str]], Iterator[_FileBlocks]]:
    """Read a whole directory with getattrlistbulk(2), which returns the same attributes as `_apfs_blocks_reader` for many entries per call, so a large Cargo target or node_modules costs far fewer system calls and path lookups."""

    libc = ctypes.CDLL(None, use_errno=True)
    getattrlistbulk = libc.getattrlistbulk
    getattrlistbulk.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint64]
    getattrlistbulk.restype = ctypes.c_int

    request = _AttrList(
        5,
        0,
        _ATTR_CMN_RETURNED_ATTRS | _ATTR_CMN_NAME | _ATTR_CMN_OBJTYPE | _ATTR_CMN_FILEID | _ATTR_CMN_ERROR,
        0,
        _ATTR_DIR_MOUNTSTATUS,
        _ATTR_FILE_LINKCOUNT | _ATTR_FILE_ALLOCSIZE,
        _ATTR_CMNEXT_PRIVATESIZE,
    )
    options = _FSOPT_ATTR_CMN_EXTENDED

    def read(directory: str, device: int, subdirectories: list[str]) -> Iterator[_FileBlocks]:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            buffer = ctypes.create_string_buffer(_BULK_BUFFER_BYTES)
            while (count := getattrlistbulk(descriptor, ctypes.byref(request), buffer, len(buffer), options)) > 0:
                entries = buffer.raw
                offset = 0
                for _ in range(count):
                    entry = _parse_bulk_entry(entries, offset, directory, device)
                    offset += _U32.unpack_from(entries, offset)[0]
                    if isinstance(entry, str):
                        subdirectories.append(entry)
                    elif entry is not None:
                        yield entry
            if count < 0:
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error), directory)
        finally:
            os.close(descriptor)

    return read


def _parse_bulk_entry(entries: bytes, offset: int, directory: str, device: int) -> str | _FileBlocks | None:
    """The subdirectory path or file blocks of one getattrlistbulk(2) entry, or None for any other entry.

    Each attribute is present only when its bit is set in the returned set, in group order and then bit order within a group, except that ATTR_CMN_ERROR comes first.
    """

    _, common, _, directory_attributes, file_attributes, extended = _BULK_ENTRY_HEADER.unpack_from(entries, offset)
    cursor = offset + _BULK_ENTRY_HEADER.size

    def take(field: struct.Struct, bit: int, returned: int) -> int | None:
        nonlocal cursor
        if not returned & bit:
            return None
        (value,) = field.unpack_from(entries, cursor)
        cursor += field.size
        return int(value)

    error = take(_U32, _ATTR_CMN_ERROR, common)
    if not common & _ATTR_CMN_NAME:
        return None
    name_offset, name_length = _ATTRIBUTE_REFERENCE.unpack_from(entries, cursor)
    start = cursor + name_offset
    path = os.path.join(directory, os.fsdecode(entries[start : start + name_length - 1]))
    cursor += _ATTRIBUTE_REFERENCE.size
    object_type = take(_U32, _ATTR_CMN_OBJTYPE, common)
    inode = take(_U64, _ATTR_CMN_FILEID, common)
    if error or object_type is None:
        return _entry_from_lstat(path, device)

    if object_type == _VDIR:
        mount_status = take(_U32, _ATTR_DIR_MOUNTSTATUS, directory_attributes) or 0
        # Another file system mounted inside frees nothing here, and a stale network mount or an automount trigger can block the walk.
        return None if mount_status & (_DIR_MNTSTATUS_MNTPOINT | _DIR_MNTSTATUS_TRIGGER) else path
    if object_type != _VREG:
        return None
    link_count = take(_U32, _ATTR_FILE_LINKCOUNT, file_attributes)
    allocated = take(_OFF_T, _ATTR_FILE_ALLOCSIZE, file_attributes)
    if inode is None or link_count is None or allocated is None:
        return _blocks_from_lstat(path)
    unshared = take(_OFF_T, _ATTR_CMNEXT_PRIVATESIZE, extended)
    return _FileBlocks(
        inode=inode,
        link_count=link_count,
        allocated_bytes=allocated,
        unshared_bytes=allocated if unshared is None else unshared,
    )


def _entry_from_lstat(path: str, device: int) -> str | _FileBlocks | None:
    try:
        status = os.lstat(path)
    except OSError:
        return None
    if stat.S_ISDIR(status.st_mode):
        return path if status.st_dev == device else None
    return _blocks_from_lstat(path)


_file_blocks: Callable[[str], _FileBlocks | None] = (
    _apfs_blocks_reader() if sys.platform == "darwin" else _blocks_from_lstat
)
_read_directory: Callable[[str, int, list[str]], Iterator[_FileBlocks]] = (
    _bulk_directory_reader() if sys.platform == "darwin" else _scandir_directory
)
