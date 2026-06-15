import uuid
from collections.abc import Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

from asgiref.sync import sync_to_async
from parameterized import parameterized
from temporalio.client import ScheduleOverlapPolicy
from temporalio.common import SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team
from posthog.temporal.common.search_attributes import POSTHOG_SCHEDULE_FINGERPRINT_KEY

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.temporal.activities import (
    delete_scanner_schedule_activity,
    list_enabled_scanners_activity,
    list_scanner_schedules_activity,
    upsert_scanner_schedule_activity,
)
from products.replay_vision.backend.temporal.constants import (
    RECONCILER_EXECUTION_TIMEOUT,
    RECONCILER_INTERVAL,
    RECONCILER_SCHEDULE_ID,
    RECONCILER_WORKFLOW_ID,
    RECONCILER_WORKFLOW_NAME,
    SCANNER_SCHEDULE_ID_PREFIX,
    SWEEP_SCANNER_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.reconciler import (
    ReconcileScannerSchedulesWorkflow,
    create_replay_vision_reconciler_schedule,
)
from products.replay_vision.backend.temporal.reconciler_types import (
    EnabledScannerEntry,
    ReconcileScannerSchedulesInputs,
    ScannerScheduleEntry,
)
from products.replay_vision.backend.temporal.schedule import (
    compute_schedule_fingerprint,
    load_enabled_scanner_fingerprints,
)


@pytest.fixture
def org_team(db) -> tuple[Organization, Team]:
    org = Organization.objects.create(name="vision-reconciler-test-org")
    team = Team.objects.create(organization=org, name="vision-reconciler-test-team")
    return org, team


def _make_scanner(team: Team, **overrides: Any) -> ReplayScanner:
    defaults: dict[str, Any] = {
        "team": team,
        "name": "reconciler-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


@pytest.mark.django_db(transaction=True)
def test_load_enabled_scanner_fingerprints_includes_only_enabled(org_team) -> None:
    _, team = org_team
    enabled = _make_scanner(team)
    _make_scanner(team, name="disabled", enabled=False)
    fingerprints = load_enabled_scanner_fingerprints()
    assert set(fingerprints.keys()) == {enabled.id}
    team_id, fingerprint = fingerprints[enabled.id]
    assert team_id == team.id
    assert isinstance(fingerprint, str) and fingerprint


@pytest.mark.django_db(transaction=True)
def test_load_enabled_scanner_fingerprints_changes_with_config(org_team) -> None:
    _, team = org_team
    scanner = _make_scanner(team, scanner_config={"prompt": "a"})
    before = load_enabled_scanner_fingerprints()[scanner.id][1]
    scanner.scanner_config = {"prompt": "b"}
    scanner.save(update_fields=["scanner_config"])
    after = load_enabled_scanner_fingerprints()[scanner.id][1]
    assert before != after


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_list_enabled_scanners_activity_returns_enabled_only(org_team) -> None:
    _, team = org_team
    enabled = await sync_to_async(_make_scanner)(team)
    await sync_to_async(_make_scanner)(team, name="disabled", enabled=False)
    entries = await list_enabled_scanners_activity()
    assert {e.scanner_id for e in entries} == {enabled.id}
    [entry] = entries
    assert entry.team_id == team.id
    assert entry.fingerprint


def _fake_listing(*, schedule_id: str, workflow_name: str, fingerprint: str | None) -> Any:
    listing = type("ScheduleListing", (), {})()
    listing.id = schedule_id
    action = type("Action", (), {"workflow": workflow_name})()
    listing.schedule = type("Schedule", (), {"action": action})()
    pairs = (
        [SearchAttributePair(key=POSTHOG_SCHEDULE_FINGERPRINT_KEY, value=fingerprint)]
        if fingerprint is not None
        else []
    )
    listing.typed_search_attributes = TypedSearchAttributes(search_attributes=pairs)
    return listing


async def _async_iter(items: list[Any]):
    for item in items:
        yield item


async def _run_list_schedules(listings: list[Any]) -> list[Any]:
    client = AsyncMock()
    client.list_schedules = AsyncMock(return_value=_async_iter(listings))
    with patch(
        "products.replay_vision.backend.temporal.activities.reconciler_activities.async_connect",
        AsyncMock(return_value=client),
    ):
        return await list_scanner_schedules_activity()


_PARSEABLE_SCANNER_ID = uuid.uuid4()


def _listing_cases() -> list[tuple[str, list[Any], list[tuple[uuid.UUID, str | None]]]]:
    return [
        (
            "parses_stamped_listing",
            [
                _fake_listing(
                    schedule_id=f"{SCANNER_SCHEDULE_ID_PREFIX}-{_PARSEABLE_SCANNER_ID}",
                    workflow_name=SWEEP_SCANNER_WORKFLOW_NAME,
                    fingerprint="abc",
                )
            ],
            [(_PARSEABLE_SCANNER_ID, "abc")],
        ),
        (
            "treats_untagged_legacy_as_none",
            [
                _fake_listing(
                    schedule_id=f"{SCANNER_SCHEDULE_ID_PREFIX}-{_PARSEABLE_SCANNER_ID}",
                    workflow_name=SWEEP_SCANNER_WORKFLOW_NAME,
                    fingerprint=None,
                )
            ],
            [(_PARSEABLE_SCANNER_ID, None)],
        ),
        (
            "skips_wrong_prefix_workflow_and_uuid",
            [
                _fake_listing(
                    schedule_id="some-other-prefix-foo",
                    workflow_name=SWEEP_SCANNER_WORKFLOW_NAME,
                    fingerprint="x",
                ),
                _fake_listing(
                    schedule_id=f"{SCANNER_SCHEDULE_ID_PREFIX}-{uuid.uuid4()}",
                    workflow_name="some-other-workflow",
                    fingerprint="x",
                ),
                _fake_listing(
                    schedule_id=f"{SCANNER_SCHEDULE_ID_PREFIX}-not-a-uuid",
                    workflow_name=SWEEP_SCANNER_WORKFLOW_NAME,
                    fingerprint="x",
                ),
            ],
            [],
        ),
    ]


@pytest.mark.asyncio
@parameterized.expand(_listing_cases())
async def test_list_scanner_schedules_activity(
    _name: str, listings: list[Any], expected: list[tuple[uuid.UUID, str | None]]
) -> None:
    entries = await _run_list_schedules(listings)
    assert [(e.scanner_id, e.fingerprint) for e in entries] == expected


class _ReconcileMocks:
    def __init__(
        self,
        *,
        enabled: list[EnabledScannerEntry],
        existing: list[ScannerScheduleEntry],
        upsert_errors_for_ids: set[uuid.UUID] | None = None,
        delete_errors_for_ids: set[uuid.UUID] | None = None,
    ) -> None:
        self.enabled = enabled
        self.existing = existing
        self.upsert_errors = upsert_errors_for_ids or set()
        self.delete_errors = delete_errors_for_ids or set()
        self.upserted: list[uuid.UUID] = []
        self.deleted: list[uuid.UUID] = []

    async def execute_activity(self, activity_fn: Any, activity_input: Any = None, **_: Any) -> Any:
        if activity_fn is list_enabled_scanners_activity:
            return self.enabled
        if activity_fn is list_scanner_schedules_activity:
            return self.existing
        if activity_fn is upsert_scanner_schedule_activity:
            if activity_input.scanner_id in self.upsert_errors:
                raise RuntimeError(f"upsert boom for {activity_input.scanner_id}")
            self.upserted.append(activity_input.scanner_id)
            return None
        if activity_fn is delete_scanner_schedule_activity:
            if activity_input.scanner_id in self.delete_errors:
                raise RuntimeError(f"delete boom for {activity_input.scanner_id}")
            self.deleted.append(activity_input.scanner_id)
            return None
        raise AssertionError(f"unexpected activity: {activity_fn!r}")


async def _run_reconcile(mocks: _ReconcileMocks):
    # `workflow.logger` reaches into the workflow runtime, which isn't set up here.
    fake_logger = type("Logger", (), {"warning": staticmethod(lambda *_a, **_kw: None)})()
    with (
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.logger", fake_logger),
    ):
        return await ReconcileScannerSchedulesWorkflow().run(ReconcileScannerSchedulesInputs())


def _enabled(*entries: tuple[uuid.UUID, int, str]) -> list[EnabledScannerEntry]:
    return [EnabledScannerEntry(scanner_id=sid, team_id=tid, fingerprint=fp) for sid, tid, fp in entries]


def _existing(*entries: tuple[uuid.UUID, str | None]) -> list[ScannerScheduleEntry]:
    return [ScannerScheduleEntry(scanner_id=sid, fingerprint=fp) for sid, fp in entries]


def _new_and_orphan() -> tuple[_ReconcileMocks, dict[str, Any]]:
    sid_new, sid_in_sync, sid_orphan = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fp = compute_schedule_fingerprint({"sample_rate": 0.5})
    return (
        _ReconcileMocks(
            enabled=_enabled((sid_new, 1, fp), (sid_in_sync, 2, fp)),
            existing=_existing((sid_in_sync, fp), (sid_orphan, fp)),
        ),
        {"upserted": [sid_new], "deleted": [sid_orphan]},
    )


def _in_sync() -> tuple[_ReconcileMocks, dict[str, Any]]:
    sid_a, sid_b = uuid.uuid4(), uuid.uuid4()
    fp = compute_schedule_fingerprint({"sample_rate": 0.1})
    return (
        _ReconcileMocks(
            enabled=_enabled((sid_a, 1, fp), (sid_b, 2, fp)),
            existing=_existing((sid_a, fp), (sid_b, fp)),
        ),
        {"upserted": [], "deleted": []},
    )


def _drift_and_legacy() -> tuple[_ReconcileMocks, dict[str, Any]]:
    sid_legacy, sid_stale, sid_clean, sid_new = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    current_fp = compute_schedule_fingerprint({"sample_rate": 0.5})
    stale_fp = compute_schedule_fingerprint({"sample_rate": 0.1})
    return (
        _ReconcileMocks(
            enabled=_enabled(
                (sid_legacy, 1, current_fp),
                (sid_stale, 2, current_fp),
                (sid_clean, 3, current_fp),
                (sid_new, 4, current_fp),
            ),
            existing=_existing((sid_legacy, None), (sid_stale, stale_fp), (sid_clean, current_fp)),
        ),
        {"upserted_set": {sid_legacy, sid_stale, sid_new}, "deleted": []},
    )


def _per_scanner_failure() -> tuple[_ReconcileMocks, dict[str, Any]]:
    sid_a, sid_b, sid_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fp = compute_schedule_fingerprint({})
    return (
        _ReconcileMocks(
            enabled=_enabled((sid_a, 1, fp), (sid_b, 2, fp), (sid_c, 3, fp)),
            existing=_existing(),
            upsert_errors_for_ids={sid_b},
        ),
        {"upserted_set": {sid_a, sid_c}, "failed_upsert": [sid_b]},
    )


def _all_failures() -> tuple[_ReconcileMocks, dict[str, Any]]:
    sid_a, sid_b, sid_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fp = compute_schedule_fingerprint({})
    return (
        _ReconcileMocks(
            enabled=_enabled((sid_a, 1, fp)),
            existing=_existing((sid_b, fp), (sid_c, fp)),
            upsert_errors_for_ids={sid_a},
            delete_errors_for_ids={sid_b, sid_c},
        ),
        {"raises": ApplicationError},
    )


def _partial_failure() -> tuple[_ReconcileMocks, dict[str, Any]]:
    sid_ok, sid_fail = uuid.uuid4(), uuid.uuid4()
    fp = compute_schedule_fingerprint({})
    return (
        _ReconcileMocks(
            enabled=_enabled((sid_ok, 1, fp), (sid_fail, 2, fp)),
            existing=_existing(),
            upsert_errors_for_ids={sid_fail},
        ),
        {"upserted": [sid_ok], "failed_upsert": [sid_fail]},
    )


@pytest.mark.asyncio
@parameterized.expand(
    [
        ("new_and_orphan", _new_and_orphan),
        ("in_sync", _in_sync),
        ("drift_and_legacy", _drift_and_legacy),
        ("per_scanner_failure_isolated", _per_scanner_failure),
        ("all_failures_raise", _all_failures),
        ("partial_failure_returns_partial", _partial_failure),
    ]
)
async def test_reconcile_workflow(_name: str, build: Callable[[], tuple[_ReconcileMocks, dict[str, Any]]]) -> None:
    mocks, expected = build()
    if expected.get("raises"):
        with pytest.raises(expected["raises"]):
            await _run_reconcile(mocks)
        return
    result = await _run_reconcile(mocks)
    if "upserted_set" in expected:
        assert set(result.upserted) == expected["upserted_set"]
    elif "upserted" in expected:
        assert result.upserted == expected["upserted"]
    if "deleted" in expected:
        assert result.deleted == expected["deleted"]
    assert result.failed_upsert == expected.get("failed_upsert", [])
    assert result.failed_delete == expected.get("failed_delete", [])


def test_reconcile_parse_inputs() -> None:
    assert ReconcileScannerSchedulesWorkflow.parse_inputs([]) == ReconcileScannerSchedulesInputs()


@pytest.mark.asyncio
@parameterized.expand([("missing", False, "create"), ("present", True, "update")])
async def test_create_reconciler_schedule_routes_by_existence(_name: str, exists: bool, expected: str) -> None:
    schedule_mod = "products.replay_vision.backend.temporal.schedule"
    with (
        patch(f"{schedule_mod}.a_schedule_exists", AsyncMock(return_value=exists)),
        patch(f"{schedule_mod}.a_create_schedule", AsyncMock()) as create,
        patch(f"{schedule_mod}.a_update_schedule", AsyncMock()) as update,
    ):
        await create_replay_vision_reconciler_schedule(AsyncMock())
    called, skipped = (create, update) if expected == "create" else (update, create)
    called.assert_awaited_once()
    skipped.assert_not_awaited()
    assert called.call_args.args[1] == RECONCILER_SCHEDULE_ID
    schedule = called.call_args.args[2]
    assert schedule.action.workflow == RECONCILER_WORKFLOW_NAME
    assert schedule.action.id == RECONCILER_WORKFLOW_ID
    assert schedule.action.task_queue == settings.REPLAY_VISION_TASK_QUEUE
    assert schedule.action.execution_timeout == RECONCILER_EXECUTION_TIMEOUT
    assert schedule.action.retry_policy.maximum_attempts == 1
    assert schedule.spec.intervals[0].every == RECONCILER_INTERVAL
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert schedule.policy.catchup_window == RECONCILER_INTERVAL
    if expected == "create":
        assert called.call_args.kwargs["trigger_immediately"] is True
    else:
        assert "trigger_immediately" not in called.call_args.kwargs
