from __future__ import annotations

from dataclasses import dataclass, field

# Bit widths of the three parts packed into one signed 64-bit `_ph_cdc_seq`. An event header stores the next
# event's offset in 32 bits, so a binlog file never passes 4 GB.
_OFFSET_BITS = 32
_FILE_NUMBER_BITS = 20
_EPOCH_BITS = 11


class BinlogStreamOutgrownError(ValueError):
    """The server rotated through more binlog files than one stream can number. A new stream starts a new count."""


@dataclass(frozen=True, slots=True, order=True)
class BinlogPosition:
    """A position in a MySQL server's binary log, as PostHog holds it.

    A binlog position is a file and a byte offset, and it only orders events on one server: after a
    failover the new server numbers its own files. The epoch counts the streams this source has
    started, so every position of a newer stream sorts after every position of an older one. Within a
    stream, files are counted from the stream's first file, so a server whose file numbers are already
    high still fits. Serialized as ``"{epoch}/{base}/{file}:{offset}"``, e.g. ``"0/3/binlog.000003:157"``.
    """

    epoch: int
    file_number: int
    offset: int
    base: int = field(compare=False)
    # The full file name, which the server needs to resume. The number orders, so the name is not compared.
    file: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not 0 <= self.epoch < 1 << _EPOCH_BITS:
            raise ValueError(f"Binlog stream epoch out of range: {self.epoch}")
        if not 0 <= self.offset < 1 << _OFFSET_BITS:
            raise ValueError(f"Binlog offset out of range: {self.offset}")
        if self.base < 0 or self.file_number < self.base:
            raise ValueError(f"Binlog file {self.file_number} precedes its stream's first file {self.base}")
        if self.file_number - self.base >= 1 << _FILE_NUMBER_BITS:
            raise BinlogStreamOutgrownError(
                f"Binlog file {self.file_number} is more than {1 << _FILE_NUMBER_BITS} files past the stream start"
            )

    @classmethod
    def at(cls, epoch: int, file: str, offset: int, base: int | None = None) -> BinlogPosition:
        """The position ``offset`` in ``file``. A new stream (``base`` None) starts counting at this file."""
        number = binlog_file_number(file)
        return cls(
            epoch=epoch, file_number=number, offset=int(offset), base=number if base is None else base, file=file
        )

    def following(self, file: str, offset: int) -> BinlogPosition:
        """A later position of the same stream."""
        return BinlogPosition.at(self.epoch, file, offset, base=self.base)

    @property
    def seq(self) -> int:
        return (
            (self.epoch << (_FILE_NUMBER_BITS + _OFFSET_BITS))
            | ((self.file_number - self.base) << _OFFSET_BITS)
            | self.offset
        )

    def serialize(self) -> str:
        return f"{self.epoch}/{self.base}/{self.file}:{self.offset}"

    @classmethod
    def deserialize(cls, value: str) -> BinlogPosition:
        epoch, _, rest = value.partition("/")
        base, _, rest = rest.partition("/")
        file, _, offset = rest.rpartition(":")
        if not epoch or not base or not file or not offset:
            raise ValueError(f"Not a binlog position: {value!r}")
        return cls.at(int(epoch), file, int(offset), base=int(base))


def binlog_file_number(file: str) -> int:
    """The index number of a binlog file, the digits after its last dot (``binlog.000123`` → 123)."""
    _, _, suffix = file.rpartition(".")
    if not suffix.isdigit():
        raise ValueError(f"Not a binlog file name: {file!r}")
    return int(suffix)
