from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from products.warehouse_sources.backend.scheduling import backend
from products.warehouse_sources.backend.scheduling.backend import (
    QUEUE_SCHEDULER_FLAG,
    clear_queue_scheduler_cache,
    queue_scheduler_firing_enabled,
    uses_queue_scheduler,
)

HELPER = "products.warehouse_sources.backend.scheduling.backend.is_schema_flag_enabled"


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_queue_scheduler_cache()


def _schema(schema_id: str = "schema-1") -> Any:
    return SimpleNamespace(id=schema_id)


@pytest.mark.parametrize("flag_value", [True, False])
def test_uses_queue_scheduler_follows_flag(flag_value: bool) -> None:
    with patch(HELPER, return_value=flag_value) as helper:
        assert uses_queue_scheduler(_schema()) is flag_value
    helper.assert_called_once()
    assert helper.call_args.args[1] == QUEUE_SCHEDULER_FLAG


def test_uses_queue_scheduler_fails_closed_and_does_not_cache_errors() -> None:
    helper = MagicMock(side_effect=[RuntimeError("boom"), True])
    with patch(HELPER, helper):
        assert uses_queue_scheduler(_schema()) is False
        assert uses_queue_scheduler(_schema()) is True
    assert helper.call_count == 2


def test_uses_queue_scheduler_caches_per_schema() -> None:
    with patch(HELPER, return_value=True) as helper:
        assert uses_queue_scheduler(_schema("a")) is True
        assert uses_queue_scheduler(_schema("a")) is True
        assert helper.call_count == 1
        assert uses_queue_scheduler(_schema("b")) is True
        assert helper.call_count == 2


def test_uses_queue_scheduler_reevaluates_after_expiry() -> None:
    clock = [1000.0]
    helper = MagicMock(side_effect=[True, False])
    with patch(HELPER, helper), patch.object(backend.time, "monotonic", side_effect=lambda: clock[0]):
        assert uses_queue_scheduler(_schema(), ttl_seconds=60) is True
        clock[0] = 1059.0
        assert uses_queue_scheduler(_schema(), ttl_seconds=60) is True
        clock[0] = 1061.0
        assert uses_queue_scheduler(_schema(), ttl_seconds=60) is False
    assert helper.call_count == 2


@pytest.mark.parametrize("value", [True, False])
def test_firing_kill_switch_reads_setting(value: bool) -> None:
    with override_settings(WAREHOUSE_QUEUE_SCHEDULER_FIRING_ENABLED=value):
        assert queue_scheduler_firing_enabled() is value


def test_firing_kill_switch_defaults_off() -> None:
    assert queue_scheduler_firing_enabled() is False
