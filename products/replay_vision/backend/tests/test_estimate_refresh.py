import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.queries import (
    ScannerVolumeEstimate,
    project_monthly_observations,
    refresh_scanner_estimate,
)
from products.replay_vision.backend.temporal.activities.list_stale_scanner_estimates import (
    list_stale_scanner_estimates_activity,
)
from products.replay_vision.backend.temporal.activities.refresh_scanner_estimate import (
    refresh_scanner_estimate_activity,
)
from products.replay_vision.backend.temporal.constants import ESTIMATES_SCHEDULE_ID
from products.replay_vision.backend.temporal.estimates import (
    RefreshScannerEstimatesWorkflow,
    create_replay_vision_estimates_schedule,
)
from products.replay_vision.backend.temporal.estimates_types import (
    RefreshScannerEstimateInputs,
    RefreshScannerEstimatesInputs,
    RefreshScannerEstimatesResult,
)

_ACTIVITY_HELPER = (
    "products.replay_vision.backend.temporal.activities.refresh_scanner_estimate.refresh_scanner_estimate"
)
_ESTIMATE_QUERY = "products.replay_vision.backend.queries.scanner_volume_estimate.estimate_scanner_session_volume"


def _make_scanner(**overrides: Any) -> ReplayScanner:
    org = Organization.objects.create(name="vision-estimate-test-org")
    team = Team.objects.create(organization=org, name="vision-estimate-test-team")
    defaults: dict[str, Any] = {
        "team": team,
        "name": "estimate-scanner",
        "scanner_type": ScannerType.MONITOR,
        "scanner_config": {"prompt": "p"},
        "model": ScannerModel.GEMINI_3_FLASH,
    }
    defaults.update(overrides)
    return ReplayScanner.objects.create(**defaults)


def _set_estimate(scanner: ReplayScanner, value: int, hours_ago: float) -> None:
    ReplayScanner.objects.filter(pk=scanner.pk).update(
        estimated_monthly_observations=value,
        estimated_at=timezone.now() - dt.timedelta(hours=hours_ago),
    )


@pytest.mark.parametrize(
    "matched, window_days, sampling_rate, expected",
    [
        (60, 30, 1.0, 60),
        (60, 30, 0.5, 30),
        (0, 30, 1.0, 0),
        (10, 1, 0.5, 150),
        (45, 30, 0.2, 9),
    ],
)
def test_project_monthly_observations(matched: int, window_days: int, sampling_rate: float, expected: int) -> None:
    estimate = ScannerVolumeEstimate(matched_sessions=matched, effective_window_days=window_days)
    assert project_monthly_observations(estimate, sampling_rate) == expected


@pytest.mark.django_db(transaction=True)
class TestRefreshScannerEstimate:
    def test_persists_projection_and_timestamp(self) -> None:
        scanner = _make_scanner(sampling_rate=0.5)
        with patch(
            _ESTIMATE_QUERY,
            return_value=ScannerVolumeEstimate(matched_sessions=60, effective_window_days=30),
        ):
            refresh_scanner_estimate(scanner)

        scanner.refresh_from_db()
        assert scanner.estimated_monthly_observations == 30
        assert scanner.estimated_at is not None

    def test_raises_and_leaves_fields_untouched_when_the_estimate_query_errors(self) -> None:
        scanner = _make_scanner()
        with patch(_ESTIMATE_QUERY, side_effect=RuntimeError("clickhouse down")):
            with pytest.raises(RuntimeError, match="clickhouse down"):
                refresh_scanner_estimate(scanner)

        scanner.refresh_from_db()
        assert scanner.estimated_monthly_observations is None
        assert scanner.estimated_at is None

    def test_does_not_bump_scanner_version(self) -> None:
        scanner = _make_scanner()
        original_version = scanner.scanner_version
        with patch(
            _ESTIMATE_QUERY,
            return_value=ScannerVolumeEstimate(matched_sessions=1, effective_window_days=30),
        ):
            refresh_scanner_estimate(scanner)

        scanner.refresh_from_db()
        assert scanner.scanner_version == original_version

    def test_discards_result_when_config_changed_mid_flight(self) -> None:
        scanner = _make_scanner(sampling_rate=1.0)

        def edit_then_estimate(**_: Any) -> ScannerVolumeEstimate:
            ReplayScanner.objects.filter(pk=scanner.pk).update(sampling_rate=0.5)
            return ScannerVolumeEstimate(matched_sessions=60, effective_window_days=30)

        with patch(_ESTIMATE_QUERY, side_effect=edit_then_estimate):
            refresh_scanner_estimate(scanner)

        scanner.refresh_from_db()
        # The estimate was computed against the pre-edit config, so the filtered write must not land.
        assert scanner.estimated_monthly_observations is None
        assert scanner.estimated_at is None


@pytest.mark.django_db(transaction=True)
class TestEstimateInvalidationOnSave:
    @pytest.mark.parametrize(
        "field, value, expect_stale",
        [
            ("sampling_rate", 0.25, True),
            ("sampling_mode", "focused", True),
            ("query", {"kind": "RecordingsQuery", "operand": "AND"}, True),
            ("name", "renamed", False),
            ("scanner_config", {"prompt": "new prompt"}, False),  # version-tracked but not a volume input
        ],
    )
    def test_volume_input_changes_clear_estimated_at(self, field: str, value: Any, expect_stale: bool) -> None:
        scanner = _make_scanner()
        _set_estimate(scanner, 10, hours_ago=1)
        scanner.refresh_from_db()

        setattr(scanner, field, value)
        scanner.save()

        scanner.refresh_from_db()
        assert (scanner.estimated_at is None) == expect_stale
        # The last computed value sticks around until the refresher recomputes it.
        assert scanner.estimated_monthly_observations == 10

    @pytest.mark.parametrize(
        "initial_enabled, new_enabled",
        [
            (False, True),  # the refresher keeps disabled scanners fresh, so re-enabling needs no invalidation
            (True, False),
            (True, True),
        ],
    )
    def test_enabled_transitions_keep_the_estimate(self, initial_enabled: bool, new_enabled: bool) -> None:
        scanner = _make_scanner(enabled=initial_enabled)
        _set_estimate(scanner, 10, hours_ago=1)
        scanner.refresh_from_db()

        scanner.enabled = new_enabled
        scanner.save(update_fields=["enabled"])

        scanner.refresh_from_db()
        assert scanner.estimated_at is not None


@pytest.mark.django_db(transaction=True)
class TestRefreshScannerEstimateActivity:
    @pytest.mark.parametrize(
        "enabled, estimated_hours_ago, expect_refresh",
        [
            (True, None, True),  # never computed → refresh
            (True, 25, True),  # stale → refresh
            (True, 1, False),  # fresh → no-op
            (False, 25, True),  # disabled scanners refresh too, so re-enabling uses an accurate number
            (False, 1, False),  # fresh → no-op regardless of enabled
        ],
    )
    def test_gates_on_staleness(self, enabled: bool, estimated_hours_ago: int | None, expect_refresh: bool) -> None:
        scanner = _make_scanner(enabled=enabled)
        if estimated_hours_ago is not None:
            _set_estimate(scanner, 10, hours_ago=estimated_hours_ago)

        with patch(_ACTIVITY_HELPER) as mock_refresh:
            refreshed = refresh_scanner_estimate_activity(
                RefreshScannerEstimateInputs(scanner_id=scanner.id, team_id=scanner.team_id)
            )

        assert refreshed == expect_refresh
        assert mock_refresh.called == expect_refresh

    def test_noop_when_scanner_missing(self) -> None:
        with patch(_ACTIVITY_HELPER) as mock_refresh:
            refreshed = refresh_scanner_estimate_activity(
                RefreshScannerEstimateInputs(scanner_id=uuid.uuid4(), team_id=999)
            )
        assert refreshed is False
        mock_refresh.assert_not_called()

    def test_propagates_helper_errors(self) -> None:
        scanner = _make_scanner()
        with patch(_ACTIVITY_HELPER, side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                refresh_scanner_estimate_activity(
                    RefreshScannerEstimateInputs(scanner_id=scanner.id, team_id=scanner.team_id)
                )


@pytest.mark.django_db(transaction=True)
class TestListStaleScannerEstimatesActivity:
    def test_returns_stale_scanners_enabled_first_then_oldest(self) -> None:
        never = _make_scanner(name="never-estimated")
        stale = _make_scanner(name="stale")
        _set_estimate(stale, 10, hours_ago=48)
        very_stale = _make_scanner(name="very-stale")
        _set_estimate(very_stale, 10, hours_ago=72)
        fresh = _make_scanner(name="fresh")
        _set_estimate(fresh, 10, hours_ago=1)
        disabled = _make_scanner(name="disabled", enabled=False)
        _set_estimate(disabled, 10, hours_ago=96)

        entries = list_stale_scanner_estimates_activity()

        # Disabled scanners are included but sort behind enabled ones even when staler.
        assert [e.scanner_id for e in entries] == [never.id, very_stale.id, stale.id, disabled.id]
        assert entries[0].team_id == never.team_id

    def test_caps_the_batch(self) -> None:
        for i in range(3):
            _make_scanner(name=f"stale-{i}")
        with patch(
            "products.replay_vision.backend.temporal.activities.list_stale_scanner_estimates.ESTIMATES_MAX_PER_RUN",
            2,
        ):
            entries = list_stale_scanner_estimates_activity()
        assert len(entries) == 2


# RefreshScannerEstimatesWorkflow (mocked-Temporal)


def _stale(*scanner_ids: uuid.UUID) -> list[RefreshScannerEstimateInputs]:
    return [RefreshScannerEstimateInputs(scanner_id=sid, team_id=i + 1) for i, sid in enumerate(scanner_ids)]


async def _run_estimates(
    stale: list[RefreshScannerEstimateInputs], failing: set[uuid.UUID] | None = None
) -> tuple[RefreshScannerEstimatesResult, list[uuid.UUID]]:
    refreshed: list[uuid.UUID] = []

    async def execute_activity(activity_fn: Any, activity_input: Any = None, **_: Any) -> Any:
        if activity_fn is list_stale_scanner_estimates_activity:
            return stale
        assert activity_fn is refresh_scanner_estimate_activity
        if activity_input.scanner_id in (failing or set()):
            raise RuntimeError(f"refresh boom for {activity_input.scanner_id}")
        refreshed.append(activity_input.scanner_id)
        return True

    with (
        patch("temporalio.workflow.execute_activity", side_effect=execute_activity),
        patch("temporalio.workflow.logger", MagicMock()),
    ):
        result = await RefreshScannerEstimatesWorkflow().run(RefreshScannerEstimatesInputs())
    return result, refreshed


@pytest.mark.asyncio
async def test_workflow_skips_when_nothing_is_stale() -> None:
    result, refreshed = await _run_estimates([])
    assert result == RefreshScannerEstimatesResult()
    assert refreshed == []


@pytest.mark.asyncio
async def test_workflow_refreshes_each_stale_scanner() -> None:
    sid_a, sid_b = uuid.uuid4(), uuid.uuid4()
    result, refreshed = await _run_estimates(_stale(sid_a, sid_b))
    assert set(result.refreshed) == {sid_a, sid_b}
    assert result.failed == []
    assert set(refreshed) == {sid_a, sid_b}


@pytest.mark.asyncio
async def test_workflow_isolates_per_scanner_failures() -> None:
    sid_ok, sid_fail = uuid.uuid4(), uuid.uuid4()
    result, _ = await _run_estimates(_stale(sid_ok, sid_fail), failing={sid_fail})
    assert result.refreshed == [sid_ok]
    assert result.failed == [sid_fail]


@pytest.mark.asyncio
async def test_workflow_raises_when_all_refreshes_fail() -> None:
    sid_a, sid_b = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ApplicationError):
        await _run_estimates(_stale(sid_a, sid_b), failing={sid_a, sid_b})


def test_refresh_estimates_parse_inputs() -> None:
    assert RefreshScannerEstimatesWorkflow.parse_inputs([]) == RefreshScannerEstimatesInputs()


@pytest.mark.asyncio
@parameterized.expand([("missing", False, "create"), ("present", True, "update")])
async def test_create_estimates_schedule_routes_by_existence(_name: str, exists: bool, expected: str) -> None:
    schedule_mod = "products.replay_vision.backend.temporal.schedule"
    with (
        patch(f"{schedule_mod}.a_schedule_exists", AsyncMock(return_value=exists)),
        patch(f"{schedule_mod}.a_create_schedule", AsyncMock()) as create,
        patch(f"{schedule_mod}.a_update_schedule", AsyncMock()) as update,
    ):
        await create_replay_vision_estimates_schedule(AsyncMock())
    called, skipped = (create, update) if expected == "create" else (update, create)
    called.assert_awaited_once()
    skipped.assert_not_awaited()
    assert called.call_args.args[1] == ESTIMATES_SCHEDULE_ID
