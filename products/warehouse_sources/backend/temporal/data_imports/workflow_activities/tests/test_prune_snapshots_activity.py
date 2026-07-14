from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import prune_snapshots as module
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.prune_snapshots import (
    PruneSnapshotsActivityInputs,
    prune_snapshots_activity,
)

_INPUTS = PruneSnapshotsActivityInputs(team_id=1, schema_id="s")


def _schema(is_append: bool) -> mock.MagicMock:
    return mock.MagicMock(
        id="s",
        name="public.orders",
        is_full_refresh_append=is_append,
        snapshot_retention_mode="count",
        snapshot_retention_value=3,
    )


def _run(schema: mock.MagicMock, *, running: bool, latest_job: object | None) -> int:
    schema_objects = mock.MagicMock()
    schema_objects.get.return_value = schema
    job_objects = mock.MagicMock()
    job_objects.filter.return_value.exists.return_value = running
    job_objects.filter.return_value.order_by.return_value.first.return_value = latest_job
    # async_to_sync(helper.prune_snapshots)(...) -> return a fixed pruned count without an event loop.
    fake_prune = mock.MagicMock(return_value=2)

    with (
        mock.patch.object(module, "close_old_connections"),
        mock.patch.object(module.ExternalDataSchema, "objects", schema_objects),
        mock.patch.object(module.ExternalDataJob, "objects", job_objects),
        mock.patch.object(module, "DeltaTableHelper") as helper_cls,
        mock.patch.object(module, "async_to_sync", return_value=fake_prune) as async_to_sync,
    ):
        result = prune_snapshots_activity(_INPUTS)

    # Expose whether the prune was actually invoked so callers can assert no-op branches.
    _run.helper_cls = helper_cls  # type: ignore[attr-defined]
    _run.async_to_sync = async_to_sync  # type: ignore[attr-defined]
    return result


def test_noop_when_not_append() -> None:
    assert _run(_schema(is_append=False), running=False, latest_job=object()) == 0
    _run.helper_cls.assert_not_called()  # type: ignore[attr-defined]


def test_noop_when_sync_running() -> None:
    assert _run(_schema(is_append=True), running=True, latest_job=object()) == 0
    _run.helper_cls.assert_not_called()  # type: ignore[attr-defined]


def test_noop_when_never_synced() -> None:
    assert _run(_schema(is_append=True), running=False, latest_job=None) == 0
    _run.helper_cls.assert_not_called()  # type: ignore[attr-defined]


def test_prunes_when_append_and_idle() -> None:
    pruned = _run(_schema(is_append=True), running=False, latest_job=object())
    assert pruned == 2
    _run.helper_cls.assert_called_once()  # type: ignore[attr-defined]
