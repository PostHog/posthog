import datetime as dt

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.models.external_data_schema import (
    SCHEDULE_INTERVAL_SECONDS_KEY,
    ExternalDataSchema,
    update_sync_type_config_keys,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.dispatch import (
    BUFFER_GENERATION_KEY,
    BUFFER_GENERATION_LOADED_KEY,
    consumer_tick_stands_down,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_trigger import (
    reconcile_schedule,
    tables_to_trigger,
    trigger_loads,
)

_API = "products.data_warehouse.backend.facade.api"
_FLAG = "products.warehouse_sources.backend.temporal.data_imports.schema_flags.is_source_flag_enabled"
_NOW = dt.datetime.now(dt.UTC)
_CAPTURE_EVERY = dt.timedelta(minutes=5)
_HOURLY = dt.timedelta(hours=1)
_SIX_HOURS = 6 * 60 * 60


def _ago(**delta: int) -> str:
    return (_NOW - dt.timedelta(**delta)).isoformat()


class TestLoadTrigger(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team=self.team, source_id="s", connection_id="c", status="Running", source_type="Postgres"
        )

    def _schema(self, name: str = "users", *, config: dict | None = None, **fields) -> ExternalDataSchema:
        return ExternalDataSchema.objects.create(
            team=self.team,
            source=self.source,
            name=name,
            sync_type=ExternalDataSchema.SyncType.CDC,
            initial_sync_complete=True,
            **{
                "status": ExternalDataSchema.Status.COMPLETED,
                "sync_frequency_interval": _CAPTURE_EVERY,
                **fields,
            },
            sync_type_config={
                "cdc_mode": "streaming",
                "cdc_table_mode": "consolidated",
                "last_full_run_at": _ago(hours=1),
                BUFFER_GENERATION_KEY: 2,
                BUFFER_GENERATION_LOADED_KEY: 2,
                **(config or {}),
            },
        )

    def _fresh(self, schema: ExternalDataSchema) -> ExternalDataSchema:
        return ExternalDataSchema.objects.select_related("source").get(id=schema.id)

    @parameterized.expand(
        [
            ("quiet", {}, {}, False),
            ("unread_writes", {}, {BUFFER_GENERATION_KEY: 3}, True),
            ("last_load_failed", {"status": ExternalDataSchema.Status.FAILED}, {}, True),
            ("full_run_due", {}, {"last_full_run_at": _ago(hours=7)}, True),
            ("snapshotting", {}, {"cdc_mode": "snapshot", BUFFER_GENERATION_KEY: 3}, False),
            ("sync_turned_off", {"should_sync": False}, {BUFFER_GENERATION_KEY: 3}, False),
            (
                "table_no_faster_than_the_full_run",
                {"sync_frequency_interval": dt.timedelta(hours=6)},
                {BUFFER_GENERATION_KEY: 3},
                False,
            ),
            (
                "hourly_table_loaded_ten_minutes_ago",
                {"sync_frequency_interval": _HOURLY},
                {BUFFER_GENERATION_KEY: 3, "last_full_run_at": _ago(minutes=10)},
                False,
            ),
            (
                "hourly_table_loaded_an_hour_ago",
                {"sync_frequency_interval": _HOURLY},
                {BUFFER_GENERATION_KEY: 3, "last_full_run_at": _ago(minutes=58)},
                True,
            ),
            (
                "hourly_table_that_failed_ten_minutes_ago",
                {"sync_frequency_interval": _HOURLY, "status": ExternalDataSchema.Status.FAILED},
                {"last_full_run_at": _ago(hours=2), "failure_streak": {"runs": 1, "last_failed_at": _ago(minutes=10)}},
                False,
            ),
        ]
    )
    def test_a_table_is_triggered_when_its_tick_would_do_work_and_its_frequency_has_passed(
        self, _name: str, fields: dict, config: dict, triggered: bool
    ) -> None:
        schema = self._fresh(self._schema(config=config, **fields))

        assert (tables_to_trigger([schema], _NOW, _CAPTURE_EVERY) == [schema]) is triggered

    def test_a_schedule_slows_down_while_the_table_streams_and_returns_when_it_stops(self) -> None:
        schema = self._schema()
        applied: list[tuple[dt.timedelta | None, bool]] = []

        def record(target: ExternalDataSchema, **kwargs) -> None:
            applied.append((target.schedule_interval, kwargs["keep_paused"]))

        with patch(f"{_API}.sync_external_data_job_workflow", side_effect=record):
            assert reconcile_schedule(self._fresh(schema), enabled=True)
            assert not reconcile_schedule(self._fresh(schema), enabled=True)
            update_sync_type_config_keys(schema.id, self.team.id, updates={"cdc_mode": "snapshot"})
            assert reconcile_schedule(self._fresh(schema), enabled=True)

        assert applied == [(dt.timedelta(hours=6), True), (_CAPTURE_EVERY, True)]
        assert SCHEDULE_INTERVAL_SECONDS_KEY not in self._fresh(schema).sync_type_config

    def test_a_failed_schedule_update_is_not_recorded_so_the_next_run_repeats_it(self) -> None:
        schema = self._fresh(self._schema())

        with patch(f"{_API}.sync_external_data_job_workflow", side_effect=RuntimeError("temporal down")):
            with pytest.raises(RuntimeError):
                reconcile_schedule(schema, enabled=True)

        assert SCHEDULE_INTERVAL_SECONDS_KEY not in schema.sync_type_config
        assert SCHEDULE_INTERVAL_SECONDS_KEY not in self._fresh(schema).sync_type_config

    def test_capture_triggers_the_tables_with_work_and_never_a_paused_schedule(self) -> None:
        owed = self._schema("owed", config={BUFFER_GENERATION_KEY: 3})
        paused = self._schema("paused", config={BUFFER_GENERATION_KEY: 3})
        self._schema("quiet")

        with (
            patch(f"{_API}.sync_external_data_job_workflow"),
            patch(f"{_API}.is_external_data_schedule_paused", side_effect=lambda id: id == str(paused.id)),
            patch(f"{_API}.trigger_external_data_workflow") as trigger,
        ):
            trigger_loads(self.source, MagicMock(), enabled=True)

        assert [call.args[0].id for call in trigger.call_args_list] == [owed.id]
        assert self._fresh(owed).sync_type_config[SCHEDULE_INTERVAL_SECONDS_KEY] == _SIX_HOURS

    def test_with_the_flag_off_capture_restores_the_schedule_and_triggers_nothing(self) -> None:
        schema = self._schema(config={BUFFER_GENERATION_KEY: 3, SCHEDULE_INTERVAL_SECONDS_KEY: _SIX_HOURS})

        with (
            patch(f"{_API}.sync_external_data_job_workflow"),
            patch(f"{_API}.trigger_external_data_workflow") as trigger,
        ):
            trigger_loads(self.source, MagicMock(), enabled=False)

        trigger.assert_not_called()
        assert SCHEDULE_INTERVAL_SECONDS_KEY not in self._fresh(schema).sync_type_config

    def test_the_run_of_a_table_that_left_streaming_restores_its_own_schedule(self) -> None:
        schema = self._schema(config={"cdc_mode": "snapshot", SCHEDULE_INTERVAL_SECONDS_KEY: _SIX_HOURS})

        with patch(_FLAG, return_value=True), patch(f"{_API}.sync_external_data_job_workflow"):
            assert consumer_tick_stands_down(schema.id, self.team.id, MagicMock()) is False

        assert SCHEDULE_INTERVAL_SECONDS_KEY not in self._fresh(schema).sync_type_config
