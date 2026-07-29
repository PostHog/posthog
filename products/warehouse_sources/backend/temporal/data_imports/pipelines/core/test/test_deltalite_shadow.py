"""Unit tests for the deltalite shadow verification.

These cover the parts that don't need the `deltalite` wheel installed (it isn't a dependency yet):
the comparison engine, the affected-partition derivation, the flag gating, and — most importantly —
the invariant that the shadow can NEVER raise into the real sync. The full seed→upsert→compare path
against real deltalite output is covered by the deltalite crate's own differential parity suite and
is validated live in the rollout canary.
"""

from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import override_settings

import pyarrow as pa

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import deltalite_shadow
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY


def _table(ids: list[str], values: list[int], parts: list[str] | None = None) -> pa.Table:
    cols: dict[str, Any] = {
        "id": pa.array(ids, pa.string()),
        "v": pa.array(values, pa.int64()),
    }
    if parts is not None:
        cols[PARTITION_KEY] = pa.array(parts, pa.string())
    return pa.table(cols)


# --------------------------------------------------------------------------------------
# _compare — the comparison engine (duckdb; no deltalite needed)
# --------------------------------------------------------------------------------------


def test_compare_identical_tables_match():
    real = _table(["a", "b", "c"], [1, 2, 3])
    shadow = _table(["c", "a", "b"], [3, 1, 2])  # same content, different row order
    is_match, diag = deltalite_shadow._compare(real, shadow, ["id"])
    assert is_match
    assert diag["rows"] == 3


def test_compare_content_mismatch_is_detected_with_pk_diagnostics():
    real = _table(["a", "b", "c"], [1, 2, 3])
    shadow = _table(["a", "b", "c"], [1, 2, 999])  # c differs
    is_match, diag = deltalite_shadow._compare(real, shadow, ["id"])
    assert not is_match
    assert diag["reason"] == "content_mismatch"
    assert diag["only_in_real"] == 1 and diag["only_in_shadow"] == 1
    # A keyed digest of the diverging PK is reported (one diverging row), never the raw value or payload.
    assert diag["diverging_pk_hashes"] == [deltalite_shadow._pk_digest(["c"])]
    assert "c" not in diag["diverging_pk_hashes"]


def test_compare_row_count_mismatch_is_detected():
    real = _table(["a", "b", "c"], [1, 2, 3])
    shadow = _table(["a", "b"], [1, 2])
    is_match, diag = deltalite_shadow._compare(real, shadow, ["id"])
    assert not is_match
    assert diag["real_rows"] == 3 and diag["shadow_rows"] == 2


def test_compare_schema_mismatch_is_detected_before_reading_rows():
    real = _table(["a"], [1])
    shadow = pa.table({"id": pa.array(["a"], pa.string()), "OTHER": pa.array([1], pa.int64())})
    is_match, diag = deltalite_shadow._compare(real, shadow, ["id"])
    assert not is_match
    assert diag["reason"] == "schema_mismatch"
    assert diag["only_real_cols"] == ["v"] and diag["only_shadow_cols"] == ["OTHER"]


def test_compare_column_order_does_not_cause_false_mismatch():
    real = pa.table({"id": pa.array(["a"]), "v": pa.array([1], pa.int64())})
    shadow = pa.table({"v": pa.array([1], pa.int64()), "id": pa.array(["a"])})  # reordered columns
    is_match, _ = deltalite_shadow._compare(real, shadow, ["id"])
    assert is_match


def test_compare_type_mismatch_is_detected_even_when_values_cast_equal():
    # Same column names and equal-looking values, but v is int32 vs int64. DuckDB EXCEPT ALL would
    # implicitly cast and report a match; the explicit type check must catch the divergence.
    real = pa.table({"id": pa.array(["a"], pa.string()), "v": pa.array([1], pa.int64())})
    shadow = pa.table({"id": pa.array(["a"], pa.string()), "v": pa.array([1], pa.int32())})
    is_match, diag = deltalite_shadow._compare(real, shadow, ["id"])
    assert not is_match
    assert diag["reason"] == "schema_type_mismatch"
    assert diag["type_mismatches"]["v"] == ["int64", "int32"]


# --------------------------------------------------------------------------------------
# _affected_partition_values
# --------------------------------------------------------------------------------------


def test_affected_partitions_partitioned():
    data = _table(["a", "b", "c"], [1, 2, 3], parts=["2026-07-01", "2026-07-01", "2026-07-02"])
    result = deltalite_shadow._affected_partition_values(data, PARTITION_KEY)
    assert result is not None
    assert sorted(result) == ["2026-07-01", "2026-07-02"]


def test_affected_partitions_unpartitioned_is_none():
    data = _table(["a", "b"], [1, 2])
    assert deltalite_shadow._affected_partition_values(data, None) is None


# --------------------------------------------------------------------------------------
# run_shadow_comparison — gating and the never-raises invariant
# --------------------------------------------------------------------------------------


def _kwargs(**over):
    base = {
        "uri": "s3://data-warehouse/team_1_stripe_abc/charges",
        "storage_options": {},
        "data": _table(["a"], [1], parts=["2026-07-01"]),
        "primary_keys": ["id"],
        "partition_key": PARTITION_KEY,
        "version_before": 3,
        "commit_metadata": None,
        "logger": AsyncMock(),
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_records_error_and_returns_when_deltalite_unavailable():
    metric = MagicMock()
    with (
        patch.object(deltalite_shadow, "_DELTALITE_AVAILABLE", False),
        patch.object(deltalite_shadow, "DELTALITE_SHADOW_TOTAL", metric),
    ):
        await deltalite_shadow.run_shadow_comparison(**_kwargs())
    metric.labels.assert_called_once_with(outcome="error")


@pytest.mark.asyncio
async def test_sampled_out_records_skipped_and_does_no_work():
    metric = MagicMock()
    with (
        override_settings(DATA_WAREHOUSE_DELTALITE_SHADOW_SAMPLE_RATE=0.0),
        patch.object(deltalite_shadow, "_DELTALITE_AVAILABLE", True),
        patch.object(deltalite_shadow, "DELTALITE_SHADOW_TOTAL", metric),
        patch.object(deltalite_shadow, "_read_affected") as read,
    ):
        await deltalite_shadow.run_shadow_comparison(**_kwargs())
    metric.labels.assert_called_once_with(outcome="skipped")
    read.assert_not_called()


@pytest.mark.asyncio
async def test_empty_batch_is_skipped():
    metric = MagicMock()
    empty = _table([], [], parts=[])
    with (
        patch.object(deltalite_shadow, "_DELTALITE_AVAILABLE", True),
        patch.object(deltalite_shadow, "DELTALITE_SHADOW_TOTAL", metric),
    ):
        await deltalite_shadow.run_shadow_comparison(**_kwargs(data=empty))
    metric.labels.assert_called_once_with(outcome="skipped")


@pytest.mark.asyncio
async def test_never_raises_and_cleans_up_on_internal_error():
    """If any step throws, the shadow records an error, swallows it, and still purges the copy."""
    metric = MagicMock()
    purge = AsyncMock()

    class _FakeS3:
        async def __aenter__(self):
            return MagicMock()

        async def __aexit__(self, *a):
            return False

    with (
        override_settings(
            DATA_WAREHOUSE_DELTALITE_SHADOW_SAMPLE_RATE=1.0,
            DATA_WAREHOUSE_DELTALITE_SHADOW_MAX_AFFECTED_BYTES=0,
            DATA_WAREHOUSE_DELTALITE_SHADOW_MAX_AFFECTED_ROWS=0,
        ),
        patch.object(deltalite_shadow, "_DELTALITE_AVAILABLE", True),
        patch.object(deltalite_shadow, "DELTALITE_SHADOW_TOTAL", metric),
        patch.object(deltalite_shadow, "_read_affected", side_effect=RuntimeError("boom")),
        patch.object(deltalite_shadow, "aget_s3_client", return_value=_FakeS3()),
        patch.object(deltalite_shadow, "_purge_s3_prefix", purge),
    ):
        # Must not raise.
        await deltalite_shadow.run_shadow_comparison(**_kwargs())

    metric.labels.assert_called_once_with(outcome="error")
    purge.assert_awaited_once()  # cleanup happened despite the error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stats",
    [
        pytest.param(None, id="size_estimate_unavailable_fails_closed"),
        pytest.param((1, 20_000_001), id="row_count_over_cap"),
    ],
)
async def test_shadow_skips_oversized_or_unknown_batch_before_materializing(stats):
    # Unknown estimate must fail closed and an over-cap row count must skip — either way the shadow
    # never materializes the slice into worker memory, so _read_affected is not reached.
    metric = MagicMock()
    with (
        patch.object(deltalite_shadow, "_DELTALITE_AVAILABLE", True),
        patch.object(deltalite_shadow, "DELTALITE_SHADOW_TOTAL", metric),
        patch.object(deltalite_shadow, "_affected_at_rest_stats", return_value=stats),
        patch.object(deltalite_shadow, "_read_affected") as read,
    ):
        await deltalite_shadow.run_shadow_comparison(**_kwargs())
    metric.labels.assert_called_once_with(outcome="skipped")
    read.assert_not_called()


# --------------------------------------------------------------------------------------
# is_deltalite_shadow_enabled — fail-closed
# --------------------------------------------------------------------------------------


def test_flag_returns_false_when_team_missing():
    with patch("posthog.models.Team") as team_cls:
        team_cls.DoesNotExist = Exception
        team_cls.objects.only.return_value.get.side_effect = team_cls.DoesNotExist
        assert deltalite_shadow.is_deltalite_shadow_enabled(1, "abc") is False


def test_flag_returns_false_when_evaluation_raises():
    fake_team = MagicMock(uuid="u", organization_id="o")
    with (
        patch("posthog.models.Team") as team_cls,
        patch.object(deltalite_shadow.posthoganalytics, "feature_enabled", side_effect=RuntimeError("flags down")),
    ):
        team_cls.objects.only.return_value.get.return_value = fake_team
        assert deltalite_shadow.is_deltalite_shadow_enabled(1, "abc") is False


def test_flag_passes_schema_id_as_person_property():
    fake_team = MagicMock(uuid="u", organization_id="o")
    with (
        patch("posthog.models.Team") as team_cls,
        patch.object(deltalite_shadow.posthoganalytics, "feature_enabled", return_value=True) as fe,
    ):
        team_cls.objects.only.return_value.get.return_value = fake_team
        assert deltalite_shadow.is_deltalite_shadow_enabled(1, "sch-123", "stripe") is True
    _, kwargs = fe.call_args
    assert kwargs["person_properties"]["schema_id"] == "sch-123"
    assert kwargs["person_properties"]["source_type"] == "stripe"
    assert kwargs["send_feature_flag_events"] is False


def test_flag_resolves_source_type_from_schema_when_not_passed():
    # When the caller omits source_type it must be resolved from the schema, otherwise a
    # `source_type = <x>` release condition can never match (the bug: it was hardcoded to None).
    fake_team = MagicMock(uuid="u", organization_id="o")
    fake_schema = MagicMock()
    fake_schema.source.source_type = "postgres"
    with (
        patch("posthog.models.Team") as team_cls,
        patch("products.warehouse_sources.backend.models.external_data_schema.ExternalDataSchema") as schema_cls,
        patch.object(deltalite_shadow.posthoganalytics, "feature_enabled", return_value=True) as fe,
    ):
        team_cls.objects.only.return_value.get.return_value = fake_team
        schema_cls.objects.select_related.return_value.get.return_value = fake_schema
        assert deltalite_shadow.is_deltalite_shadow_enabled(1, "sch-9") is True
    _, kwargs = fe.call_args
    assert kwargs["person_properties"]["source_type"] == "postgres"
