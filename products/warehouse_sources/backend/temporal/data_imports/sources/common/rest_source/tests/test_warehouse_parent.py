from pathlib import Path

import pytest
from unittest.mock import patch

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import warehouse_parent
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.warehouse_parent import (
    WarehouseParentTableNotFoundError,
    iter_parent_pages_from_warehouse,
)


def _write_parent_table(tmp_path: Path) -> str:
    uri = str(tmp_path / "issues")
    # Physical columns are snake_case — the Delta writer normalizes API field names.
    table = pa.table(
        {
            "id": ["1", "2", "3"],
            "last_seen": ["2026-03-01", "2026-03-03", "2026-03-02"],
            "title": ["a", "b", "c"],
        }
    )
    deltalake.write_deltalake(uri, table)
    return uri


def _patched_reader(uri: str, **kwargs):
    with (
        patch.object(warehouse_parent, "_parent_table_uri", return_value=uri),
        patch.object(warehouse_parent, "get_delta_storage_options", return_value={}),
    ):
        return list(
            iter_parent_pages_from_warehouse(
                team_id=1,
                source_id="00000000-0000-0000-0000-000000000000",
                parent_name="issues",
                **kwargs,
            )
        )


def test_reader_pages_and_rekeys_to_api_field_names(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    pages = _patched_reader(uri, columns=["id", "lastSeen"], page_size=2)

    assert [len(page) for page in pages] == [2, 1]
    rows = [row for page in pages for row in page]
    # Keys come back as the API field names, values from the snake_case physical columns,
    # and only the requested columns are present.
    assert {row["id"]: row["lastSeen"] for row in rows} == {
        "1": "2026-03-01",
        "2": "2026-03-03",
        "3": "2026-03-02",
    }
    assert all(set(row) == {"id", "lastSeen"} for row in rows)


def test_reader_order_by_descending(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    pages = _patched_reader(uri, columns=["id", "lastSeen"], page_size=10, order_by=("lastSeen", "descending"))

    rows = [row for page in pages for row in page]
    assert [row["id"] for row in rows] == ["2", "3", "1"]


def test_reader_raises_when_table_missing(tmp_path: Path) -> None:
    with pytest.raises(WarehouseParentTableNotFoundError, match="no synced table"):
        _patched_reader(str(tmp_path / "does_not_exist"), columns=["id"], page_size=10)


def test_reader_raises_when_requested_columns_missing(tmp_path: Path) -> None:
    uri = _write_parent_table(tmp_path)

    # A partial miss must fail loudly upfront too — a silently dropped column would surface
    # later as an opaque resolve error mid-sync.
    with pytest.raises(
        WarehouseParentTableNotFoundError, match=r"missing requested column\(s\) \['definitely_missing'\]"
    ):
        _patched_reader(uri, columns=["id", "definitely_missing"], page_size=10)


def test_reader_dedupes_append_mode_duplicates(tmp_path: Path) -> None:
    uri = str(tmp_path / "issues")
    # Append-mode parents accumulate one row per sync per parent id.
    table = pa.table(
        {
            "id": ["1", "2", "1", "3", "2"],
            "last_seen": ["2026-03-01", "2026-03-02", "2026-03-05", "2026-03-03", "2026-03-04"],
        }
    )
    deltalake.write_deltalake(uri, table)

    pages = _patched_reader(
        uri, columns=["id", "lastSeen"], page_size=10, order_by=("lastSeen", "descending"), dedupe_by="id"
    )

    rows = [row for page in pages for row in page]
    # One row per id, first (freshest, given descending order) occurrence wins.
    assert [(row["id"], row["lastSeen"]) for row in rows] == [
        ("1", "2026-03-05"),
        ("2", "2026-03-04"),
        ("3", "2026-03-03"),
    ]
