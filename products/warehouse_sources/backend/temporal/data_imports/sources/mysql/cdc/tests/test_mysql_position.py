import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition

# In stream order: offsets within a file, the next file, then a failover to a server with lower file numbers.
_FIRST = BinlogPosition.at(0, "binlog.000003", 157)
# In stream order: offsets within a file, later files, a server whose file numbers passed six digits, then a
# failover to a server with lower file numbers.
_STREAM_ORDER = [
    _FIRST,
    _FIRST.following("binlog.000003", 4_000_000_000),
    _FIRST.following("binlog.000004", 4),
    _FIRST.following("binlog.999999", 120),
    BinlogPosition.at(1, "binlog.2000000", 4),
    BinlogPosition.at(1, "binlog.2000000", 4).following("binlog.2000001", 4),
    BinlogPosition.at(2, "binlog.000001", 4),
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
            ("no_base", "0/binlog.000003:157"),
            ("no_offset", "0/3/binlog.000003"),
            ("no_file_number", "0/3/binlog:157"),
            ("epoch_overflow", "2048/3/binlog.000003:157"),
            ("file_before_the_stream_start", "0/3/binlog.000002:157"),
            ("more_files_than_a_stream_numbers", "0/3/binlog.1048579:157"),
        ]
    )
    def test_malformed_position_is_refused(self, _name, serialized):
        with pytest.raises(ValueError):
            BinlogPosition.deserialize(serialized)
