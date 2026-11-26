import datetime as dt

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    request_manual_runs,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.dispatch import (
    BUFFER_GENERATION_KEY,
    BUFFER_GENERATION_LOADED_KEY,
    BUFFER_GENERATION_SEEN_KEY,
    BUFFER_WRITE_OPEN_KEY,
    TickDecision,
    consumer_tick_decision,
    consumer_tick_stands_down,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import CDC_RESET_PENDING_KEY
from products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager import (
    BUFFER_LISTED_AT_KEY,
    ListingProof,
    read_completed_listing_proof,
)

_MANAGER = "products.warehouse_sources.backend.temporal.data_imports.cdc.source_manager"
_FLAG = "products.warehouse_sources.backend.temporal.data_imports.schema_flags.is_source_flag_enabled"
_NOW = dt.datetime.now(dt.UTC)


class TestConsumerTickDecision(BaseTest):
    def _schema(self, *, config: dict | None = None, **fields) -> ExternalDataSchema:
        source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Postgres"
        )
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=source,
            name="users",
            sync_type=ExternalDataSchema.SyncType.CDC,
            initial_sync_complete=True,
            **{"status": ExternalDataSchema.Status.COMPLETED, **fields},
            sync_type_config={
                "cdc_mode": "streaming",
                "cdc_table_mode": "consolidated",
                "last_full_run_at": (_NOW - dt.timedelta(hours=1)).isoformat(),
                BUFFER_GENERATION_KEY: 2,
                BUFFER_GENERATION_LOADED_KEY: 2,
                **(config or {}),
            },
        )

    def _completed_listing(self, schema: ExternalDataSchema, generation_seen: int) -> None:
        ExternalDataJob.objects.create(
            team=self.team,
            pipeline=schema.source,
            schema=schema,
            status=ExternalDataJob.Status.COMPLETED,
            rows_synced=0,
            schema_snapshot={
                BUFFER_LISTED_AT_KEY: dt.datetime.now(dt.UTC).isoformat(),
                BUFFER_GENERATION_SEEN_KEY: generation_seen,
            },
        )

    def _decide(self, schema: ExternalDataSchema, *, flag: bool = True) -> TickDecision | None:
        schema = ExternalDataSchema.objects.select_related("source").get(id=schema.id)
        with patch(_FLAG, return_value=flag):
            return consumer_tick_decision(schema, _NOW)

    @parameterized.expand(
        [
            ("quiet", {}, None, TickDecision.STOOD_DOWN),
            ("write_open", {BUFFER_WRITE_OPEN_KEY: True}, 5, TickDecision.OWED),
            ("new_writes_and_no_listing", {BUFFER_GENERATION_KEY: 3}, None, TickDecision.OWED),
            ("new_writes_listed_before_they_were_counted", {BUFFER_GENERATION_KEY: 3}, 2, TickDecision.OWED),
            ("new_writes_read_by_a_completed_run", {BUFFER_GENERATION_KEY: 3}, 3, TickDecision.STOOD_DOWN),
            ("never_proven", {BUFFER_GENERATION_LOADED_KEY: None, BUFFER_GENERATION_KEY: 0}, None, TickDecision.OWED),
            (
                "heartbeat_due",
                {"last_full_run_at": (_NOW - dt.timedelta(hours=7)).isoformat()},
                None,
                TickDecision.HEARTBEAT,
            ),
            ("never_ran_a_full_tick", {"last_full_run_at": None}, None, TickDecision.HEARTBEAT),
            (
                "owed_with_the_heartbeat_due",
                {BUFFER_WRITE_OPEN_KEY: True, "last_full_run_at": None},
                None,
                TickDecision.OWED,
            ),
        ]
    )
    def test_a_streaming_table_runs_only_when_a_load_or_its_heartbeat_is_owed(
        self, _name: str, config: dict, listed_generation: int | None, expected: TickDecision
    ) -> None:
        schema = self._schema(config=config)
        if listed_generation is not None:
            self._completed_listing(schema, listed_generation)

        assert self._decide(schema) == expected

    def test_a_write_counted_while_the_tick_reads_stays_owed(self) -> None:
        schema = self._schema(config={BUFFER_GENERATION_KEY: 3})
        self._completed_listing(schema, 3)

        def counted_meanwhile(read_schema: ExternalDataSchema) -> ListingProof | None:
            update_sync_type_config_keys(schema.id, self.team.id, updates={BUFFER_GENERATION_KEY: 4})
            return read_completed_listing_proof(read_schema)

        with patch(f"{_MANAGER}.read_completed_listing_proof", side_effect=counted_meanwhile):
            assert self._decide(schema) == TickDecision.STOOD_DOWN

        assert self._decide(schema) == TickDecision.OWED

    def test_a_sync_someone_asked_for_runs_until_a_full_run_finishes(self) -> None:
        schema = self._schema()

        request_manual_runs([schema.id], self.team.id)
        assert self._decide(schema) is None

        update_sync_type_config_keys(
            schema.id, self.team.id, updates={"last_full_run_at": dt.datetime.now(dt.UTC).isoformat()}
        )
        assert self._decide(schema) == TickDecision.STOOD_DOWN

    def test_a_proven_read_is_recorded_so_later_ticks_need_no_job_read(self) -> None:
        schema = self._schema(config={BUFFER_GENERATION_KEY: 3})
        self._completed_listing(schema, 3)

        assert self._decide(schema) == TickDecision.STOOD_DOWN
        schema.refresh_from_db()
        assert schema.sync_type_config[BUFFER_GENERATION_LOADED_KEY] == 3

        ExternalDataJob.objects.filter(schema=schema).delete()
        assert self._decide(schema) == TickDecision.STOOD_DOWN

    @parameterized.expand(
        [
            ("reset_requested", {"config": {"reset_pipeline": True}}, True),
            ("snapshotting", {"config": {"cdc_mode": "snapshot"}}, True),
            ("resnapshot_pending", {"config": {CDC_RESET_PENDING_KEY: {"generation": 1}}}, True),
            ("ad_hoc_run_paused_the_schedule", {"config": {"admin_unpause_schedule_after_run": "wf-ad-hoc"}}, True),
            ("last_run_failed", {"status": ExternalDataSchema.Status.FAILED}, True),
            ("billing_limited", {"status": ExternalDataSchema.Status.BILLING_LIMIT_REACHED}, True),
            ("flag_off", {}, False),
        ]
    )
    def test_the_gate_never_holds_back_a_tick_that_today_does_work(self, _name: str, fields: dict, flag: bool) -> None:
        schema = self._schema(**fields)

        assert self._decide(schema, flag=flag) is None

    def test_a_gate_error_lets_the_tick_run(self) -> None:
        schema = self._schema()

        with patch(f"{consumer_tick_decision.__module__}.consumer_tick_decision", side_effect=RuntimeError("db down")):
            assert consumer_tick_stands_down(schema.id, self.team.id, MagicMock()) is False
