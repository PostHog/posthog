import uuid
import asyncio
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import deltalake
from parameterized import parameterized

from posthog.models.team import Team

from products.warehouse_sources.backend.models.external_data_schema import HISTORY_TRACKED_SINCE_KEY, ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import WEBHOOK_EVENT_HIDDEN_COLUMNS
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import HISTORY_NAMING
from products.warehouse_sources.backend.temporal.data_imports.incremental_history import (
    IncrementalHistoryUnavailableError,
    stage_history_batch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import evolve_pyarrow_schema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.history_upsert import (
    HistoryFinalizeResult,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.test.helpers import make_logger
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.writer import DeltaWriter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import SourceDriver
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_event_columns import (
    EVENT_ID_COLUMN,
    WEBHOOK_EVENT_COLUMNS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.github import (
    GithubAuthMethodConfig,
    GithubSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stripe import (
    StripeAuthMethodConfig,
    StripeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.source import GithubSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stripe.source import StripeSource
from products.warehouse_sources.backend.temporal.data_imports.webhook_history import (
    SEED_EVENT_ID,
    attach_webhook_history_lanes,
    finalize_run_history,
    history_events_batch,
    main_table_order_columns,
    newest_events_batch,
)

_T1, _T2, _T3 = (datetime(2026, 3, 1, hour, tzinfo=UTC) for hour in (1, 2, 3))
_MODULE = "products.warehouse_sources.backend.temporal.data_imports.webhook_history"


@dataclasses.dataclass(frozen=True)
class _Source:
    source_type: str
    schema_name: str
    driver: Callable[[], SourceDriver]
    event: Callable[[str, datetime, str], dict[str, Any]]
    statuses: tuple[str, str, str, str]


def _stripe_event(name: str, at: datetime, status: str) -> dict[str, Any]:
    invoice = {"id": "in_1", "object": "invoice", "status": status}
    return {"id": f"evt_{name}", "type": "invoice.updated", "created": int(at.timestamp()), "data": {"object": invoice}}


def _github_job(name: str, at: datetime, status: str) -> dict[str, Any]:
    started = at.isoformat() if status in ("in_progress", "completed", "waiting") else None
    return {
        "id": 7,
        "status": status,
        "created_at": (_T1 if started else at).isoformat(),
        "started_at": started,
        "completed_at": at.isoformat() if status == "completed" else None,
    }


_STRIPE = _Source(
    "Stripe",
    "Invoice",
    lambda: SourceDriver(
        StripeSource(),
        StripeSourceConfig(auth_method=StripeAuthMethodConfig(selection="api_key", stripe_secret_key="sk_test")),
        webhook_files=_FILES,
    ),
    _stripe_event,
    ("draft", "draft", "open", "paid"),
)
_GITHUB = _Source(
    "Github",
    "workflow_jobs",
    lambda: SourceDriver(
        GithubSource(),
        GithubSourceConfig(
            auth_method=GithubAuthMethodConfig(github_integration_id=None, selection="pat", personal_access_token="t"),
            repository="acme/widgets",
            repositories=None,
        ),
        webhook_files=_FILES,
    ),
    _github_job,
    ("queued", "waiting", "in_progress", "completed"),
)
_FILES: list[list[dict[str, Any]]] = []


@dataclasses.dataclass
class _Loaded:
    history: HistoryFinalizeResult | None
    rows_older_than_main: int


class _Warehouse:
    """One webhook table on local Delta tables, loaded as the loader loads each lane of a run."""

    def __init__(self, root: Path, source: _Source, *, history: bool, tracked_since: datetime = _T1) -> None:
        self.root, self.source, self.history = root, source, history
        self.schema = ExternalDataSchema(
            name=source.schema_name,
            team=Team(id=1, organization_id=uuid.uuid4()),
            source=ExternalDataSource(source_type=source.source_type),
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"cdc_table_mode": "both", HISTORY_TRACKED_SINCE_KEY: tracked_since.isoformat()},
        )
        self._runs = 0

    def sync(self, *events: tuple[str, datetime, str]) -> _Loaded:
        _FILES[:] = [[self.source.event(*event) for event in events]]
        result = self.source.driver().run(self.source.schema_name, [], webhook_history=self.history)
        assert result.raised is None
        # As the pipeline does before the lanes, which types a column of only nulls as text.
        batch = evolve_pyarrow_schema(pa.concat_tables(result.items, promote_options="permissive"), None)
        self._runs += 1
        return asyncio.run(self._load(batch, f"run{self._runs}"))

    async def _load(self, batch: pa.Table, run_uuid: str) -> _Loaded:
        main_batch, finalized = batch, None
        if self.history:
            # The two lanes load apart. History goes first here, so a seed reads the main table before the run.
            history_ref = self._ref(f"{self.source.schema_name}_history")
            history = history_events_batch(batch, schema_name="t", naming=HISTORY_NAMING, fallback_time=_T1)
            await stage_history_batch(history_ref, history, primary_keys=["id"], run_uuid=run_uuid, batch_index=0)
            finalized = await finalize_run_history(
                history_ref, ["id"], schema=self.schema, run_uuid=run_uuid, batch_index=0
            )
            main_batch = newest_events_batch(batch, primary_keys=["id"], fallback_time=_T1)
        writer = DeltaWriter(self._ref(self.source.schema_name))
        await writer.write(
            main_batch,
            "incremental",
            should_overwrite_table=False,
            primary_keys=["id"],
            order_columns=main_table_order_columns(self.schema, main_batch.column_names),
        )
        return _Loaded(finalized, writer.rows_older_than_main)

    def _ref(self, resource_name: str) -> DeltaTableRef:
        return DeltaTableRef(resource_name=resource_name, job=MagicMock(), logger=make_logger())

    def main(self) -> list[dict[str, Any]]:
        return deltalake.DeltaTable(str(self.root / self.source.schema_name)).to_pyarrow_table().to_pylist()

    def versions(self) -> list[tuple[str, datetime, datetime | None]]:
        rows = deltalake.DeltaTable(str(self.root / f"{self.source.schema_name}_history")).to_pyarrow_table()
        ordered = sorted(
            rows.to_pylist(), key=lambda r: (r["_ph_valid_from"], r["_ph_valid_to"] is None, r["_ph_event_rank"])
        )
        return [(r["status"], r["_ph_valid_from"], r["_ph_valid_to"]) for r in ordered]


@pytest.fixture
def local_tables(tmp_path: Path):
    async def _uri(ref: DeltaTableRef) -> str:
        return str(tmp_path / ref.resource_name)

    with (
        patch.object(DeltaTableRef, "_get_delta_table_uri", autospec=True, side_effect=_uri),
        patch.object(DeltaTableRef, "_get_credentials", return_value={}),
    ):
        yield tmp_path


@pytest.mark.parametrize("source", [_STRIPE, _GITHUB], ids=["stripe", "github"])
def test_late_events_go_into_the_past_and_never_replace_the_main_row(local_tables: Path, source: _Source) -> None:
    first, late, outranked, tie = source.statuses
    warehouse = _Warehouse(local_tables, source, history=True)
    warehouse.sync(("1", _T1, first), ("3", _T3, outranked))

    late_sync = warehouse.sync(("2", _T2, late), ("1", _T1, first))

    assert late_sync.history is not None
    assert (late_sync.history.rows_late, late_sync.history.versions_split) == (1, 1)
    assert late_sync.history.rows_redelivered == 1
    assert late_sync.rows_older_than_main == 1
    assert [row["status"] for row in warehouse.main()] == [outranked]

    warehouse.sync(("4", _T3, tie))

    assert [row["status"] for row in warehouse.main()] == [tie]
    assert warehouse.versions() == [
        (first, _T1, _T2),
        (late, _T2, _T3),
        (outranked, _T3, _T3),
        (tie, _T3, None),
    ]


@pytest.mark.parametrize("source", [_STRIPE, _GITHUB], ids=["stripe", "github"])
def test_without_history_the_last_arrival_still_wins(local_tables: Path, source: _Source) -> None:
    first, late, outranked, _ = source.statuses
    warehouse = _Warehouse(local_tables, source, history=False)
    warehouse.sync(("1", _T1, first), ("3", _T3, outranked))

    warehouse.sync(("2", _T2, late))

    assert [row["status"] for row in warehouse.main()] == [late]
    assert not set(WEBHOOK_EVENT_COLUMNS) & set(warehouse.main()[0])
    assert not (local_tables / f"{source.schema_name}_history").exists()


def test_history_turned_on_seeds_the_main_rows_from_when_tracking_began(local_tables: Path) -> None:
    tracked_since = _T1 - timedelta(days=1)
    off = _Warehouse(local_tables, _STRIPE, history=False)
    off.sync(("1", _T1, "draft"))
    on = _Warehouse(local_tables, _STRIPE, history=True, tracked_since=tracked_since)

    on.sync(("3", _T3, "open"))

    assert on.versions() == [("draft", tracked_since, _T3), ("open", _T3, None)]
    seeded = next(row for row in on.main() if row["status"] == "open")
    assert seeded[EVENT_ID_COLUMN] == "evt_3"
    history = deltalake.DeltaTable(str(local_tables / "Invoice_history")).to_pyarrow_table().to_pylist()
    assert {row[EVENT_ID_COLUMN] for row in history} == {SEED_EVENT_ID, "evt_3"}


@parameterized.expand(
    [
        ("declares_events", "Invoice", "both", True),
        ("one_row_per_event_already", "CustomerPaymentMethodHistory", "both", False),
        ("consolidated", "Invoice", "consolidated", False),
    ]
)
def test_keeps_history_for_a_webhook_table_whose_source_declares_events(
    _name: str, schema_name: str, mode: str, expected: bool
) -> None:
    schema = ExternalDataSchema(
        name=schema_name,
        source=ExternalDataSource(source_type="Stripe"),
        sync_type=ExternalDataSchema.SyncType.WEBHOOK,
        sync_type_config={"cdc_table_mode": mode},
    )

    assert schema.keeps_history is expected


class TestAttachWebhookHistoryLanes:
    def _schema(self, mode: str, config: dict[str, Any] | None = None) -> ExternalDataSchema:
        return ExternalDataSchema(
            name="Invoice",
            team=Team(id=1, organization_id=uuid.uuid4()),
            source=ExternalDataSource(source_type="Stripe"),
            sync_type=ExternalDataSchema.SyncType.WEBHOOK,
            sync_type_config={"cdc_table_mode": mode, "primary_key_columns": ["id"], **(config or {})},
        )

    def _attach(self, schema: ExternalDataSchema, *, webhook_history: bool = True) -> SourceResponse:
        response = SourceResponse(name="Invoice", items=lambda: iter([]), primary_keys=["id"])
        with (
            patch(f"{_MODULE}.history_lane_naming", return_value=HISTORY_NAMING),
            patch(
                f"{_MODULE}.update_sync_type_config_keys",
                side_effect=lambda *_, mutate: (mutate(config := dict(schema.sync_type_config)), config)[1],
            ) as save,
        ):
            attach_webhook_history_lanes(schema, response, webhook_history=webhook_history)
        self.saves = save.call_count
        return response

    def test_first_run_with_history_stamps_when_tracking_began_once(self) -> None:
        schema = self._schema("both")

        response = self._attach(schema)
        stamped = schema.sync_type_config[HISTORY_TRACKED_SINCE_KEY]
        self._attach(schema)

        assert [lane.name for lane in response.lanes or []] == ["Invoice", "Invoice_history"]
        assert self.saves == 0
        assert schema.sync_type_config[HISTORY_TRACKED_SINCE_KEY] == stamped

    @parameterized.expand([("both", None), ("cdc_only", IncrementalHistoryUnavailableError)])
    def test_flag_off_skips_both_tables_and_refuses_history_only(self, mode: str, error: type | None) -> None:
        schema = self._schema(mode)
        if error is None:
            assert not self._attach(schema, webhook_history=False).lanes
        else:
            with pytest.raises(error):
                self._attach(schema, webhook_history=False)


def test_catalog_hides_every_webhook_event_column() -> None:
    assert WEBHOOK_EVENT_HIDDEN_COLUMNS == frozenset(WEBHOOK_EVENT_COLUMNS)
