from __future__ import annotations

from dataclasses import dataclass, field

# Bit widths of the three parts packed into one signed 64-bit `_ph_cdc_seq`. A binlog file is at most 1 GB
# (`max_binlog_size`) unless one transaction overflows it, and its index suffix has six digits.
_OFFSET_BITS = 32
_FILE_NUMBER_BITS = 20
_EPOCH_BITS = 11


@dataclass(frozen=True, slots=True, order=True)
class BinlogPosition:
    """A position in a MySQL server's binary log, as PostHog holds it.

    A binlog position is a file and a byte offset, and it only orders events on one server: after a
    failover the new server numbers its own files. The epoch counts the streams this source has
    started, so every position of a newer stream sorts after every position of an older one.
    Serialized as ``"{epoch}/{file}:{offset}"``, e.g. ``"0/binlog.000003:157"``.
    """

    epoch: int
    file_number: int
    offset: int
    # The full file name, which the server needs to resume. The number orders, so the name is not compared.
    file: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not 0 <= self.epoch < 1 << _EPOCH_BITS:
            raise ValueError(f"Binlog stream epoch out of range: {self.epoch}")
        if not 0 <= self.file_number < 1 << _FILE_NUMBER_BITS:
            raise ValueError(f"Binlog file number out of range: {self.file_number}")
        if not 0 <= self.offset < 1 << _OFFSET_BITS:
            raise ValueError(f"Binlog offset out of range: {self.offset}")

    @classmethod
    def at(cls, epoch: int, file: str, offset: int) -> BinlogPosition:
        return cls(epoch=epoch, file_number=binlog_file_number(file), offset=int(offset), file=file)

    @property
    def seq(self) -> int:
        return (self.epoch << (_FILE_NUMBER_BITS + _OFFSET_BITS)) | (self.file_number << _OFFSET_BITS) | self.offset

    def serialize(self) -> str:
        return f"{self.epoch}/{self.file}:{self.offset}"

    @classmethod
    def deserialize(cls, value: str) -> BinlogPosition:
        epoch, _, rest = value.partition("/")
        file, _, offset = rest.rpartition(":")
        if not epoch or not file or not offset:
            raise ValueError(f"Not a binlog position: {value!r}")
        return cls.at(int(epoch), file, int(offset))


def binlog_file_number(file: str) -> int:
    """The index number of a binlog file, the digits after its last dot (``binlog.000123`` → 123)."""
    _, _, suffix = file.rpartition(".")
    if not suffix.isdigit():
        raise ValueError(f"Not a binlog file name: {file!r}")
    return int(suffix)
