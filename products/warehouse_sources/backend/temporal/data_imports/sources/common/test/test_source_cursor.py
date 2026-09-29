from collections.abc import Mapping
from typing import Any, ClassVar

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import (
    CursorSource,
    SourceCursorManager,
)


@frozen
class _OffsetsCursor:
    cursor_kind: ClassVar[str] = "offsets"

    offsets: dict[str, int]


class _OffsetsSource(CursorSource[_OffsetsCursor]):
    def cursor_class(self) -> type[_OffsetsCursor]:
        return _OffsetsCursor

    def merge_cursors(self, current: _OffsetsCursor, candidate: _OffsetsCursor) -> _OffsetsCursor:
        merged = dict(current.offsets)
        for partition, offset in candidate.offsets.items():
            merged[partition] = max(offset, merged.get(partition, offset))
        return _OffsetsCursor(offsets=merged)

    def cursor_from_legacy(self, sync_type_config: Mapping[str, Any]) -> _OffsetsCursor | None:
        legacy = sync_type_config.get("legacy_offsets")
        return _OffsetsCursor(offsets=legacy) if legacy is not None else None


def _manager(sync_type_config: dict[str, Any] | None) -> SourceCursorManager[_OffsetsCursor]:
    return SourceCursorManager.from_sync_type_config(_OffsetsSource(), sync_type_config, MagicMock())


class TestSourceCursorManager:
    @parameterized.expand(
        [
            ("no_config_means_a_rebuild", None, None),
            ("empty_config", {}, None),
            ("stored_cursor", {"source_cursor": {"kind": "offsets", "data": {"offsets": {"0": 5}}}}, {"0": 5}),
            (
                "unknown_fields_from_a_newer_deploy_are_dropped",
                {"source_cursor": {"kind": "offsets", "data": {"offsets": {"0": 5}, "added_later": 1}}},
                {"0": 5},
            ),
            ("cursor_of_another_kind", {"source_cursor": {"kind": "postgres_xmin", "data": {"offsets": {}}}}, None),
            ("cursor_missing_a_field", {"source_cursor": {"kind": "offsets", "data": {}}}, None),
            ("malformed_payload", {"source_cursor": "not-a-mapping"}, None),
            ("legacy_keys_when_no_cursor", {"legacy_offsets": {"0": 3}}, {"0": 3}),
            (
                "stored_cursor_wins_over_legacy_keys",
                {"source_cursor": {"kind": "offsets", "data": {"offsets": {"0": 5}}}, "legacy_offsets": {"0": 3}},
                {"0": 5},
            ),
        ]
    )
    def test_load(self, _name: str, sync_type_config: dict[str, Any] | None, expected: dict[str, int] | None) -> None:
        loaded = _manager(sync_type_config).load()
        assert (loaded.offsets if loaded is not None else None) == expected

    @parameterized.expand(
        [
            ("no_stored_cursor_takes_the_candidate", None, {"0": 1, "1": 7}),
            ("stage_merges_against_the_stored_cursor", {"0": 5, "1": 2}, {"0": 5, "1": 7}),
        ]
    )
    def test_stage(self, _name: str, stored: dict[str, int] | None, expected: dict[str, int]) -> None:
        config = None if stored is None else {"source_cursor": {"kind": "offsets", "data": {"offsets": stored}}}
        manager = _manager(config)

        manager.stage(_OffsetsCursor(offsets={"0": 1, "1": 7}))

        assert manager.staged_payload() == {"kind": "offsets", "data": {"offsets": expected}}

    def test_nothing_staged_has_no_payload(self) -> None:
        assert _manager({}).staged_payload() is None

    def test_get_cursor_manager_requires_a_manager_on_the_inputs(self) -> None:
        with pytest.raises(ValueError):
            _OffsetsSource().get_cursor_manager(MagicMock(source_cursor=None))
