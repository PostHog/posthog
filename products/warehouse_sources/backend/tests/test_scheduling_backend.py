from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.test import override_settings

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team

from products.warehouse_sources.backend.scheduling import backend
from products.warehouse_sources.backend.scheduling.backend import (
    QUEUE_SCHEDULER_FLAG,
    TeamQueueOwnership,
    clear_queue_scheduler_cache,
    queue_scheduler_firing_enabled,
    uses_queue_scheduler,
)

HELPER = "products.warehouse_sources.backend.scheduling.backend.is_schema_flag_enabled"
FEATURE_ENABLED = "products.warehouse_sources.backend.scheduling.backend.posthoganalytics.feature_enabled"


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


def test_uses_queue_scheduler_prunes_expired_entries_when_cache_is_full() -> None:
    clock = [1000.0]
    with (
        patch(HELPER, return_value=True),
        patch.object(backend, "_PRUNE_THRESHOLD", 3),
        patch.object(backend.time, "monotonic", side_effect=lambda: clock[0]),
    ):
        for schema_id in ("a", "b", "c"):
            uses_queue_scheduler(_schema(schema_id), ttl_seconds=60)
        clock[0] = 1061.0
        uses_queue_scheduler(_schema("d"), ttl_seconds=60)
    assert set(backend._cache) == {"d"}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.django_db
class TestTeamQueueOwnership:
    def test_evaluates_once_per_team_until_the_ttl_expires(self) -> None:
        organization = create_organization("ownership org")
        flagged, unflagged = create_team(organization=organization), create_team(organization=organization)
        clock = _Clock()
        ownership = TeamQueueOwnership(ttl_seconds=60, clock=clock)
        answers = {str(flagged.uuid): True, str(unflagged.uuid): False}

        with patch(FEATURE_ENABLED, side_effect=lambda flag, distinct_id, **_: answers[distinct_id]) as flag:
            # One tick asks for the team of every due schema, with repeats.
            assert ownership.owned_teams([flagged.pk, flagged.pk, unflagged.pk]) == {flagged.pk}
            assert ownership.owned_teams([flagged.pk, unflagged.pk]) == {flagged.pk}
            assert flag.call_count == 2
            assert {call.args[0] for call in flag.call_args_list} == {QUEUE_SCHEDULER_FLAG}

            clock.now += 61
            answers[str(flagged.uuid)] = False
            assert ownership.owned_teams([flagged.pk]) == frozenset()
            assert flag.call_count == 3

    def test_a_failed_evaluation_counts_as_unflagged_and_is_asked_again(self) -> None:
        team = create_team(organization=create_organization("ownership org"))
        ownership = TeamQueueOwnership(clock=_Clock())

        with patch(FEATURE_ENABLED, side_effect=[RuntimeError("flags down"), True]) as flag:
            assert ownership.owned_teams([team.pk]) == frozenset()
            assert ownership.owned_teams([team.pk]) == {team.pk}
        assert flag.call_count == 2

    def test_a_missing_team_is_not_owned(self) -> None:
        with patch(FEATURE_ENABLED, return_value=True) as flag:
            assert TeamQueueOwnership().owned_teams([987654321]) == frozenset()
        flag.assert_not_called()

    def test_a_team_lookup_failure_is_not_cached(self) -> None:
        team = create_team(organization=create_organization("ownership org"))
        ownership = TeamQueueOwnership(clock=_Clock())

        with patch(FEATURE_ENABLED, return_value=True):
            with patch.object(backend.Team.objects, "filter", side_effect=OperationalError("db down")):
                assert ownership.owned_teams([team.pk]) == frozenset()
            assert ownership.owned_teams([team.pk]) == {team.pk}
