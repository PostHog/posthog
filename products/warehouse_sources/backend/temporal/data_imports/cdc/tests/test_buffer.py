import io
import random
from contextlib import contextmanager

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import CDC_SEQ_COLUMN
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    BufferFileSpan,
    CDCBufferWriter,
    build_buffer_file_name,
    get_buffer_prefix,
    parse_buffer_file_name,
)


class TestBufferFileName:
    def test_roundtrip(self):
        name = build_buffer_file_name(256, 512, 3)
        assert parse_buffer_file_name(name) == BufferFileSpan(start_seq=256, end_seq=512, file_index=3)

    def test_rejects_foreign_names(self):
        assert parse_buffer_file_name("part-0000.parquet") is None
        assert parse_buffer_file_name("schema.json") is None
        assert parse_buffer_file_name("256-512-3.parquet") is None  # unpadded
        assert parse_buffer_file_name(build_buffer_file_name(1, 2, 3).removesuffix(".parquet")) is None

    def test_rejects_non_canonical_numeric_spellings(self):
        # int() accepts these; the contract must not — they break lexicographic order.
        base = build_buffer_file_name(100, 200, 0)
        assert parse_buffer_file_name(base.replace("-", "-+", 1)) is None
        assert parse_buffer_file_name("0000000000000001_000-" + base.split("-", 1)[1]) is None
        assert parse_buffer_file_name(" " + base[1:]) is None
        assert parse_buffer_file_name(base.replace("0", "０", 1)) is None  # fullwidth digit

    def test_build_rejects_out_of_contract_values(self):
        with pytest.raises(ValueError, match="range"):
            build_buffer_file_name(300, 200, 0)  # inverted
        with pytest.raises(ValueError, match="range"):
            build_buffer_file_name(-1, 200, 0)
        with pytest.raises(ValueError, match="index"):
            build_buffer_file_name(1, 2, 10**6)  # would emit 7 digits and break sort
        with pytest.raises(ValueError, match="index"):
            build_buffer_file_name(1, 2, -1)

    def test_lexicographic_sort_equals_numeric_sort(self):
        # The consumer's only ordering primitive is a filename sort — padding must
        # make that equal to numeric (start, end, index) order across magnitudes.
        ranges = [(1, 9, 0), (10, 15, 0), (15, 15, 1), (15, 15, 2), (16, 2**63 - 1, 0), (2**40, 2**41, 5)]
        names = [build_buffer_file_name(*r) for r in ranges]
        shuffled = names[:]
        random.Random(42).shuffle(shuffled)
        assert sorted(shuffled) == [build_buffer_file_name(*r) for r in sorted(ranges)]


class TestIsShadowWriteEnabled:
    """The per-team flag is the single gate, and it fails closed."""

    def _call(self, *, flag, team_lookup_ok: bool = True) -> bool:
        from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import is_shadow_write_enabled

        team = MagicMock(uuid="team-uuid", id=2, organization_id="org-uuid")
        team_manager = MagicMock()
        team_manager.objects.get.return_value = team
        if not team_lookup_ok:
            team_manager.objects.get.side_effect = Exception("db down")

        flag_fn = MagicMock(side_effect=flag) if callable(flag) else MagicMock(return_value=flag)
        with (
            patch.dict("sys.modules", {"posthog.models.team": MagicMock(Team=team_manager)}),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.posthoganalytics.feature_enabled",
                flag_fn,
            ),
        ):
            result = is_shadow_write_enabled(2, MagicMock())
        self._last_flag_call = flag_fn
        return result

    def test_follows_the_flag(self):
        assert self._call(flag=True) is True
        assert self._call(flag=False) is False

    def test_passes_team_scoped_targeting_context(self):
        # team_id drives the release conditions (warehouse per-team rollout convention),
        # so a soak covers single teams rather than whole orgs.
        self._call(flag=True)
        kwargs = self._last_flag_call.call_args.kwargs
        assert kwargs["person_properties"]["team_id"] == "2"
        assert kwargs["groups"]["project"] == "2"

    def test_flag_service_failure_disables_rather_than_raises(self):
        def boom(*_a, **_k):
            raise RuntimeError("flag service down")

        assert self._call(flag=boom) is False

    def test_team_lookup_failure_disables_rather_than_raises(self):
        assert self._call(flag=True, team_lookup_ok=False) is False


class TestCDCBufferWriter:
    def _writer_with_captured_files(self) -> tuple[CDCBufferWriter, dict[str, io.BytesIO]]:
        files: dict[str, io.BytesIO] = {}

        @contextmanager
        def fake_open(path, mode):
            buf = io.BytesIO()
            files[path] = buf
            yield buf

        mock_s3 = MagicMock()
        mock_s3.open = fake_open
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.get_s3_client",
                return_value=mock_s3,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.ensure_bucket"),
        ):
            writer = CDCBufferWriter(MagicMock())
        return writer, files

    def _table(self, seqs: list[int]) -> pa.Table:
        return pa.table(
            {
                "id": pa.array(range(len(seqs)), type=pa.int64()),
                CDC_SEQ_COLUMN: pa.array(seqs, type=pa.int64()),
            }
        )

    def test_writes_window_file_with_range_from_seq_column(self):
        writer, files = self._writer_with_captured_files()
        result = writer.write_batch(team_id=1, schema_id="abc", table=self._table([512, 256, 300]), file_index=2)

        assert result.start_seq == 256
        assert result.end_seq == 512
        assert result.row_count == 3
        assert result.s3_path == f"{get_buffer_prefix(1, 'abc')}/{build_buffer_file_name(256, 512, 2)}"

        assert len(files) == 1
        written = pq.read_table(io.BytesIO(next(iter(files.values())).getvalue()))
        assert written.column(CDC_SEQ_COLUMN).to_pylist() == [512, 256, 300]

    def test_rejects_empty_table(self):
        writer, _files = self._writer_with_captured_files()
        with pytest.raises(ValueError, match="empty"):
            writer.write_batch(team_id=1, schema_id="abc", table=self._table([]), file_index=0)

    def test_rejects_table_without_seq_column(self):
        writer, _files = self._writer_with_captured_files()
        table = pa.table({"id": pa.array([1], type=pa.int64())})
        with pytest.raises(ValueError, match=CDC_SEQ_COLUMN):
            writer.write_batch(team_id=1, schema_id="abc", table=table, file_index=0)

    def test_rejects_any_null_seq(self):
        # pc.min_max skips nulls, so a partially-null column would silently
        # narrow the filename's range — reject nulls outright.
        writer, files = self._writer_with_captured_files()
        for seqs in ([None], [256, None, 512]):
            table = pa.table(
                {
                    "id": pa.array(range(len(seqs)), type=pa.int64()),
                    CDC_SEQ_COLUMN: pa.array(seqs, type=pa.int64()),
                }
            )
            with pytest.raises(ValueError, match="non-null"):
                writer.write_batch(team_id=1, schema_id="abc", table=table, file_index=0)
        assert not files

    def test_failed_write_removes_the_partial_object(self):
        # fsspec close() flushes buffered bytes even after a failure, so the key
        # must be removed or a truncated file lands under a contract-valid name.
        files: dict[str, io.BytesIO] = {}

        @contextmanager
        def fake_open(path, mode):
            buf = io.BytesIO()
            files[path] = buf
            yield buf

        mock_s3 = MagicMock()
        mock_s3.open = fake_open
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.get_s3_client",
                return_value=mock_s3,
            ),
            patch("products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.ensure_bucket"),
        ):
            writer = CDCBufferWriter(MagicMock())
        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.pq.write_table",
                side_effect=OSError("mid-write failure"),
            ),
            pytest.raises(OSError),
        ):
            writer.write_batch(team_id=1, schema_id="abc", table=self._table([256]), file_index=0)
        mock_s3.rm.assert_called_once_with(next(iter(files)))

    def test_cleanup_superseded_files_removes_at_or_past_restart(self):
        writer, _files = self._writer_with_captured_files()
        prefix = "data-warehouse/cdc_producer/1/abc"
        keys = [
            f"{prefix}/{build_buffer_file_name(100, 200, 0)}",  # settled, below restart
            f"{prefix}/{build_buffer_file_name(300, 400, 1)}",  # superseded
            f"{prefix}/{build_buffer_file_name(300, 300, 2)}",  # superseded, shared boundary
            f"{prefix}/schema.json",  # foreign — never touched
        ]
        writer._s3.ls = MagicMock(return_value=keys)
        writer._s3.rm = MagicMock()

        removed = writer.cleanup_superseded_files(team_id=1, schema_id="abc", restart_seq=300)

        # A cached listing that misses a fresh file silently skips its supersede-delete.
        assert writer._s3.ls.call_args.kwargs["refresh"] is True
        assert removed == 2
        removed_keys = [c.args[0] for c in writer._s3.rm.call_args_list]
        assert removed_keys == keys[1:3]

    def test_cleanup_handles_missing_prefix(self):
        writer, _files = self._writer_with_captured_files()
        writer._s3.ls = MagicMock(side_effect=FileNotFoundError)
        assert writer.cleanup_superseded_files(team_id=1, schema_id="abc", restart_seq=1) == 0
