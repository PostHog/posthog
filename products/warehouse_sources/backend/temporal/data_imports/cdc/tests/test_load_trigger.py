import datetime as dt
from types import SimpleNamespace

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
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.load_trigger import (
    LOAD_TRIGGERED_AT_KEY,
    reconcile_schedule,
    restore_own_schedule,
    tables_to_trigger,
    trigger_loads,
)

_API = "products.data_warehouse.backend.facade.api"
_TRIGGER = "products.warehouse_sources.backend.temporal.data_imports.cdc.load_trigger"
_SCHEDULE = "posthog.temporal.common.schedule"
_FLAG = "products.warehouse_sources.backend.temporal.data_imports.schema_flags.is_source_flag_enabled"
_NOW = dt.datetime.now(dt.UTC)
_CAPTURE_EVERY = dt.timedelta(minutes=5)
_HOURLY = dt.timedelta(hours=1)
_SIX_HOURS = 6 * 60 * 60
_UNREAD = {BUFFER_GENERATION_KEY: 3}
_SLOWED = {SCHEDULE_INTERVAL_SECONDS_KEY: _SIX_HOURS}


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
            initial_sync_complete=True,
            **{
                "sync_type": ExternalDataSchema.SyncType.CDC,
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

    def _trigger_loads(self, *, enabled: bool = True, paused: set | None = None, update_error: bool = False) -> list:
        triggered: list = []
        describe = lambda _client, schedule_id: SimpleNamespace(  # noqa: E731
            schedule=SimpleNamespace(state=SimpleNamespace(paused=schedule_id in {str(id) for id in paused or ()}))
        )
        with (
            patch(
                f"{_API}.sync_external_data_job_workflow",
                side_effect=RuntimeError("temporal down") if update_error else None,
            ),
            patch("posthog.temporal.common.client.sync_connect"),
            patch(f"{_SCHEDULE}.describe_schedule", side_effect=describe),
            patch(
                f"{_SCHEDULE}.trigger_schedule", side_effect=lambda _client, schedule_id: triggered.append(schedule_id)
            ),
        ):
            trigger_loads(self.source, MagicMock(), enabled=enabled)
        return triggered

    @parameterized.expand(
        [
            ("quiet", {}, {}, True, False),
            ("unread_writes", {}, _UNREAD, True, True),
            (
                "unread_writes_triggered_earlier_in_this_capture_run",
                {},
                {**_UNREAD, LOAD_TRIGGERED_AT_KEY: _ago(minutes=2)},
                True,
                False,
            ),
            (
                "unread_writes_triggered_by_the_last_capture_run",
                {},
                {**_UNREAD, LOAD_TRIGGERED_AT_KEY: _ago(minutes=5)},
                True,
                True,
            ),
            ("last_load_failed", {"status": ExternalDataSchema.Status.FAILED}, {}, True, True),
            ("full_run_due", {}, {"last_full_run_at": _ago(hours=7)}, True, True),
            ("snapshotting", {}, {"cdc_mode": "snapshot", **_UNREAD}, True, False),
            ("sync_turned_off", {"should_sync": False}, _UNREAD, True, False),
            ("flag_off", {}, _UNREAD, False, False),
            ("flag_off_but_the_schedule_is_still_slowed", {}, {**_UNREAD, **_SLOWED}, False, True),
            ("snapshotting_but_the_schedule_is_still_slowed", {}, {"cdc_mode": "snapshot", **_SLOWED}, True, True),
            ("no_faster_than_the_full_run", {"sync_frequency_interval": dt.timedelta(hours=6)}, _UNREAD, True, False),
            ("hourly_and_never_triggered", {"sync_frequency_interval": _HOURLY}, _UNREAD, True, True),
            (
                "hourly_and_triggered_ten_minutes_ago",
                {"sync_frequency_interval": _HOURLY},
                {**_UNREAD, LOAD_TRIGGERED_AT_KEY: _ago(minutes=10)},
                True,
                False,
            ),
            (
                "hourly_and_triggered_an_hour_ago",
                {"sync_frequency_interval": _HOURLY},
                {**_UNREAD, LOAD_TRIGGERED_AT_KEY: _ago(minutes=58)},
                True,
                True,
            ),
            (
                "hourly_at_the_billing_limit_and_triggered_ten_minutes_ago",
                {"sync_frequency_interval": _HOURLY, "status": ExternalDataSchema.Status.BILLING_LIMIT_REACHED},
                {LOAD_TRIGGERED_AT_KEY: _ago(minutes=10)},
                True,
                False,
            ),
        ]
    )
    def test_a_table_is_triggered_when_its_tick_would_do_work_and_its_frequency_has_passed(
        self, _name: str, fields: dict, config: dict, enabled: bool, triggered: bool
    ) -> None:
        schema = self._fresh(self._schema(config=config, **fields))

        assert (tables_to_trigger([schema], _NOW, _CAPTURE_EVERY, enabled=enabled) == [schema]) is triggered

    def test_a_schedule_slows_down_while_the_table_streams_and_returns_when_it_stops(self) -> None:
        schema = self._schema()
        applied: list[tuple[dt.timedelta | None, bool, bool]] = []

        def record(target: ExternalDataSchema, **kwargs) -> None:
            applied.append((target.schedule_interval, kwargs["should_sync"], kwargs["keep_paused"]))

        with patch(f"{_API}.sync_external_data_job_workflow", side_effect=record):
            assert reconcile_schedule(self._fresh(schema), enabled=True)
            assert not reconcile_schedule(self._fresh(schema), enabled=True)
            update_sync_type_config_keys(schema.id, self.team.id, updates={"cdc_mode": "snapshot"})
            assert reconcile_schedule(self._fresh(schema), enabled=True)

        # Neither call may pause or unpause the schedule.
        assert applied == [(dt.timedelta(hours=6), True, True), (_CAPTURE_EVERY, True, True)]
        assert SCHEDULE_INTERVAL_SECONDS_KEY not in self._fresh(schema).sync_type_config

    def test_a_failed_schedule_update_is_not_recorded_so_the_next_run_repeats_it(self) -> None:
        schema = self._fresh(self._schema())

        with patch(f"{_API}.sync_external_data_job_workflow", side_effect=RuntimeError("temporal down")):
            with pytest.raises(RuntimeError):
                reconcile_schedule(schema, enabled=True)

        assert schema.schedule_interval_override is None
        assert self._fresh(schema).schedule_interval_override is None

    def test_capture_triggers_the_tables_with_work_and_never_a_paused_schedule(self) -> None:
        owed = self._schema("owed", config=_UNREAD)
        hourly = self._schema("hourly", config=_UNREAD, sync_frequency_interval=_HOURLY)
        paused = self._schema("paused", config=_UNREAD)
        self._schema("quiet")

        triggered = self._trigger_loads(paused={paused.id})

        assert sorted(triggered) == sorted([str(owed.id), str(hourly.id)])
        assert self._fresh(owed).schedule_interval_override == dt.timedelta(hours=6)
        # The stamp is what spaces a table's triggers out, and a skipped trigger must not count.
        assert LOAD_TRIGGERED_AT_KEY in self._fresh(hourly).sync_type_config
        assert LOAD_TRIGGERED_AT_KEY not in self._fresh(paused).sync_type_config

    @parameterized.expand(
        [
            ("flag_turned_off", {}, {}),
            ("table_left_cdc", {"sync_type": ExternalDataSchema.SyncType.INCREMENTAL}, {}),
            ("table_reset_to_snapshot", {}, {"cdc_mode": "snapshot"}),
        ]
    )
    def test_capture_restores_a_schedule_that_should_no_longer_be_slowed(
        self, name: str, fields: dict, config: dict
    ) -> None:
        schema = self._schema(config={**_SLOWED, **config}, **fields)

        triggered = self._trigger_loads(enabled=name != "flag_turned_off")

        assert triggered == []
        assert self._fresh(schema).schedule_interval_override is None

    def test_a_table_whose_restore_fails_keeps_being_triggered(self) -> None:
        schema = self._schema(config={**_UNREAD, **_SLOWED})

        triggered = self._trigger_loads(enabled=False, update_error=True)

        assert triggered == [str(schema.id)]
        assert self._fresh(schema).schedule_interval_override == dt.timedelta(hours=6)

    def test_slowdowns_that_fail_still_count_against_the_cap(self) -> None:
        for name in ("a", "b", "c"):
            self._schema(name)
        with (
            patch(f"{_TRIGGER}.MAX_SCHEDULE_SLOWDOWNS_PER_RUN", 2),
            patch(f"{_TRIGGER}.reconcile_schedule", side_effect=RuntimeError("temporal down")) as reconcile,
        ):
            self._trigger_loads()

        assert reconcile.call_count == 2

    def test_restores_are_never_held_back_by_the_cap_on_slowdowns(self) -> None:
        restored = self._schema("a_reset", config={"cdc_mode": "snapshot", **_SLOWED})
        streaming = [self._schema(name) for name in ("b", "c")]

        with patch(f"{_TRIGGER}.MAX_SCHEDULE_SLOWDOWNS_PER_RUN", 1):
            self._trigger_loads()

        assert self._fresh(restored).schedule_interval_override is None
        assert sum(self._fresh(s).schedule_interval_override is not None for s in streaming) == 1

    def test_the_run_of_a_table_that_left_cdc_restores_its_own_schedule(self) -> None:
        schema = self._schema(config=_SLOWED, sync_type=ExternalDataSchema.SyncType.INCREMENTAL)

        with patch(_FLAG, return_value=True), patch(f"{_API}.sync_external_data_job_workflow"):
            restore_own_schedule(schema.id, self.team.id, MagicMock())

        assert self._fresh(schema).schedule_interval_override is None
