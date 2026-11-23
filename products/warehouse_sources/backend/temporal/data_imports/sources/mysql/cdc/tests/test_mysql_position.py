import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition

# In stream order: offsets within a file, the next file, then a failover to a server with lower file numbers.
_STREAM_ORDER = [
    BinlogPosition.at(0, "binlog.000003", 157),
    BinlogPosition.at(0, "binlog.000003", 4_000_000_000),
    BinlogPosition.at(0, "binlog.000004", 4),
    BinlogPosition.at(0, "mysql-bin-changelog.999999", 120),
    BinlogPosition.at(1, "binlog.000001", 4),
    BinlogPosition.at(2047, "binlog.000001", 4),
]


class TestBinlogPosition:
    def test_seq_increases_along_the_stream_and_across_failovers(self):
        seqs = [position.seq for position in _STREAM_ORDER]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        assert all(0 <= seq < 1 << 63 for seq in seqs)

    @parameterized.expand([(position.serialize(),) for position in _STREAM_ORDER])
    def test_serialized_position_round_trips(self, serialized):
        position = BinlogPosition.deserialize(serialized)
        assert position.serialize() == serialized
        assert BinlogPosition.deserialize(position.serialize()).seq == position.seq

    @parameterized.expand(
        [
            ("no_epoch", "binlog.000003:157"),
            ("no_offset", "0@binlog.000003"),
            ("no_file_number", "0@binlog:157"),
            ("epoch_overflow", "2048@binlog.000003:157"),
            ("file_number_overflow", "0@binlog.1048576:157"),
        ]
    )
    def test_malformed_position_is_refused(self, _name, serialized):
        with pytest.raises(ValueError):
            BinlogPosition.deserialize(serialized)
