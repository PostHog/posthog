import uuid
import datetime as dt
from contextlib import contextmanager
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.client import ScheduleActionStartWorkflow
from temporalio.service import RPCError, RPCStatusCode

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.constants import (
    SCANNER_SCHEDULE_ID_PREFIX,
    SCANNER_SCHEDULE_INTERVAL,
    SCANNER_SCHEDULE_TYPE,
    scanner_schedule_id,
)
from products.replay_vision.backend.temporal.schedule import (
    _build_schedule,
    _compute_offset,
    _load_fingerprint,
    a_delete_scanner_schedule,
    a_upsert_scanner_schedule,
    compute_schedule_fingerprint,
)
from products.replay_vision.backend.temporal.sweep_types import SweepScannerInputs

_MODULE = "products.replay_vision.backend.temporal.schedule"


@pytest.fixture
def org_team(db) -> tuple[Organization, Team]:
    org = Organization.objects.create(name="vision-schedule-test-org")
    team = Team.objects.create(organization=org, name="vision-schedule-test-team")
    return org, team


def _make_scanner(team: Team, **overrides: Any) -> ReplayScanner:
    defaults: dict[str, Any] = {
        "team": team,
        "name": "schedule-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


def _rpc_error(status: RPCStatusCode) -> RPCError:
    return RPCError("rpc failure", status, b"")


@contextmanager
def _patched_temporal(
    *,
    exists: bool,
    create_side_effect: BaseException | None = None,
    delete_side_effect: BaseException | None = None,
    exists_side_effect: BaseException | None = None,
):
    # The MagicMock client is intentionally permissive: helpers receive it as a positional arg
    # and are themselves mocked here, so attribute access on the client itself is never exercised.
    create = AsyncMock(side_effect=create_side_effect)
    update = AsyncMock()
    delete = AsyncMock(side_effect=delete_side_effect)
    exists_mock = AsyncMock(return_value=exists, side_effect=exists_side_effect)
    with (
        patch(f"{_MODULE}.async_connect", AsyncMock(return_value=MagicMock())),
        patch(f"{_MODULE}.a_schedule_exists", exists_mock),
        patch(f"{_MODULE}.a_create_schedule", create),
        patch(f"{_MODULE}.a_update_schedule", update),
        patch(f"{_MODULE}.a_delete_schedule", delete),
    ):
        yield exists_mock, create, update, delete


def test_schedule_id_format() -> None:
    sid = uuid.UUID("c232d230-484b-4342-8d88-c70718a796b7")
    assert scanner_schedule_id(sid) == f"{SCANNER_SCHEDULE_ID_PREFIX}-{sid}"


def test_offset_is_deterministic_per_scanner() -> None:
    sid = uuid.uuid4()
    assert _compute_offset(sid) == _compute_offset(sid)


def test_offset_within_interval() -> None:
    interval_s = int(SCANNER_SCHEDULE_INTERVAL.total_seconds())
    for _ in range(50):
        offset = _compute_offset(uuid.uuid4())
        assert dt.timedelta(0) <= offset < dt.timedelta(seconds=interval_s)


def test_offset_distributes_across_window() -> None:
    offsets = {_compute_offset(uuid.uuid4()).total_seconds() for _ in range(100)}
    assert len(offsets) > 50


@parameterized.expand(
    [
        (
            "stable_across_calls",
            {"a": 1, "b": [1, 2], "c": {"nested": True}},
            {"a": 1, "b": [1, 2], "c": {"nested": True}},
            True,
        ),
        ("key_order_independent", {"x": 1, "y": 2}, {"y": 2, "x": 1}, True),
        ("changes_on_field_change", {"scanner_version": 1}, {"scanner_version": 2}, False),
        ("none_equals_empty_dict", None, {}, True),
    ]
)
def test_fingerprint(_name: str, snapshot_a: Any, snapshot_b: Any, should_equal: bool) -> None:
    actual_equal = compute_schedule_fingerprint(snapshot_a) == compute_schedule_fingerprint(snapshot_b)
    assert actual_equal is should_equal


def test_build_schedule_carries_scanner_inputs_and_offset() -> None:
    scanner_id = uuid.uuid4()
    schedule = _build_schedule(scanner_id, team_id=99)
    action = schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert action.workflow == "replay-vision-sweep-scanner"
    inputs = action.args[0]
    assert isinstance(inputs, SweepScannerInputs)
    assert inputs.scanner_id == scanner_id
    assert inputs.team_id == 99
    assert schedule.spec.intervals[0].every == SCANNER_SCHEDULE_INTERVAL
    assert schedule.spec.intervals[0].offset == _compute_offset(scanner_id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_creates_when_missing(org_team) -> None:
    _, team = org_team
    scanner = await sync_to_async(_make_scanner)(team)
    with _patched_temporal(exists=False) as (_exists, create, update, _delete):
        await a_upsert_scanner_schedule(scanner.id, scanner.team_id)
    create.assert_awaited_once()
    update.assert_not_awaited()
    assert create.call_args.kwargs["trigger_immediately"] is True
    keys = {pair.key.name for pair in create.call_args.kwargs["search_attributes"]}
    assert {"PostHogTeamId", "PostHogScheduleType", "PostHogScheduleFingerprint"} <= keys


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_updates_when_present(org_team) -> None:
    _, team = org_team
    scanner = await sync_to_async(_make_scanner)(team)
    with _patched_temporal(exists=True) as (_exists, create, update, _delete):
        await a_upsert_scanner_schedule(scanner.id, scanner.team_id)
    update.assert_awaited_once()
    create.assert_not_awaited()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_deletes_when_scanner_missing() -> None:
    with _patched_temporal(exists=True) as (_exists, create, _update, delete):
        await a_upsert_scanner_schedule(uuid.uuid4(), team_id=99)
    create.assert_not_awaited()
    delete.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_deletes_when_scanner_disabled(org_team) -> None:
    _, team = org_team
    scanner = await sync_to_async(_make_scanner)(team, enabled=False)
    with _patched_temporal(exists=True) as (_exists, create, _update, delete):
        await a_upsert_scanner_schedule(scanner.id, scanner.team_id)
    create.assert_not_awaited()
    delete.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_falls_back_to_update_on_already_exists(org_team) -> None:
    _, team = org_team
    scanner = await sync_to_async(_make_scanner)(team)
    with _patched_temporal(exists=False, create_side_effect=_rpc_error(RPCStatusCode.ALREADY_EXISTS)) as (
        _exists,
        create,
        update,
        _delete,
    ):
        await a_upsert_scanner_schedule(scanner.id, scanner.team_id)
    create.assert_awaited_once()
    update.assert_awaited_once()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_propagates_non_already_exists_rpc_error(org_team) -> None:
    _, team = org_team
    scanner = await sync_to_async(_make_scanner)(team)
    with _patched_temporal(exists=False, create_side_effect=_rpc_error(RPCStatusCode.UNAVAILABLE)):
        with pytest.raises(RPCError):
            await a_upsert_scanner_schedule(scanner.id, scanner.team_id)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_upsert_stamps_fingerprint_attribute(org_team) -> None:
    _, team = org_team
    scanner = await sync_to_async(_make_scanner)(team)
    expected = await sync_to_async(_load_fingerprint)(scanner.id)
    with _patched_temporal(exists=False) as (_exists, create, _update, _delete):
        await a_upsert_scanner_schedule(scanner.id, scanner.team_id)
    pairs = {pair.key.name: pair.value for pair in create.call_args.kwargs["search_attributes"]}
    assert pairs["PostHogTeamId"] == scanner.team_id
    assert pairs["PostHogScheduleType"] == SCANNER_SCHEDULE_TYPE
    assert pairs["PostHogScheduleFingerprint"] == expected


@parameterized.expand(
    [
        ("noop_when_schedule_missing", False, None, False, None),
        ("calls_delete_when_present", True, None, True, None),
        ("swallows_not_found_race", True, RPCStatusCode.NOT_FOUND, True, None),
        ("propagates_other_rpc_errors", True, RPCStatusCode.UNAVAILABLE, True, RPCError),
    ]
)
@pytest.mark.asyncio
async def test_delete_scanner_schedule(
    _name: str,
    exists: bool,
    delete_status: RPCStatusCode | None,
    expect_delete_awaited: bool,
    expect_raises: type[BaseException] | None,
) -> None:
    delete_side_effect = _rpc_error(delete_status) if delete_status else None
    with _patched_temporal(exists=exists, delete_side_effect=delete_side_effect) as (_exists, _create, _update, delete):
        if expect_raises is not None:
            with pytest.raises(expect_raises):
                await a_delete_scanner_schedule(uuid.uuid4())
        else:
            await a_delete_scanner_schedule(uuid.uuid4())
    if expect_delete_awaited:
        delete.assert_awaited_once()
    else:
        delete.assert_not_awaited()
