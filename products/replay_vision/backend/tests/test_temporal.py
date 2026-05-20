import uuid
import datetime as dt
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

import psycopg.errors
from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError

from posthog.models import Organization, Team
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.models.replay_lens import LensModel, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.temporal import ApplyLensWorkflow
from products.replay_vision.backend.temporal.activities.call_lens_provider import call_lens_provider_activity
from products.replay_vision.backend.temporal.activities.cleanup_gemini_file import cleanup_gemini_file_activity
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.activities.emit_observation_event import emit_observation_event_activity
from products.replay_vision.backend.temporal.activities.ensure_session_asset import ensure_session_asset_activity
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_events_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
    mark_observation_succeeded_activity,
)
from products.replay_vision.backend.temporal.activities.upload_video_to_gemini import upload_video_to_gemini_activity
from products.replay_vision.backend.temporal.lenses.monitor import MonitorOutput
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import (
    ApplyLensInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    EnsureSessionAssetInputs,
    EnsureSessionAssetOutput,
    EventTable,
    FetchSessionEventsInputs,
    LensCallOutput,
    LensLlmInputs,
    LensResult,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
    UploadedVideo,
)
from products.replay_vision.backend.tests.helpers import snapshot_for as _snapshot_for


def _make_lens() -> ReplayLens:
    org = Organization.objects.create(name="vision-test-org")
    team = Team.objects.create(organization=org, name="vision-test-team")
    return ReplayLens.objects.create(
        team=team,
        name="t",
        lens_type=LensType.MONITOR,
        lens_config={"prompt": "p"},
        model=LensModel.GEMINI_3_FLASH,
    )


def _make_observation(lens: ReplayLens, **overrides) -> ReplayObservation:
    defaults: dict = {
        "lens": lens,
        "team": lens.team,
        "session_id": "sess-1",
        "triggered_by": ObservationTrigger.ON_DEMAND,
        "lens_snapshot": _snapshot_for(lens),
    }
    defaults.update(overrides)
    return ReplayObservation.objects.create(**defaults)


@pytest.mark.django_db(transaction=True)
class TestCreateObservationActivity:
    def test_creates_row_in_pending_with_workflow_id_and_snapshot(self) -> None:
        lens = _make_lens()
        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-xyz",
            )
        )

        assert result.was_created is True
        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.status == ObservationStatus.PENDING
        assert observation.workflow_id == "wf-xyz"
        assert observation.session_id == "sess-1"
        assert observation.triggered_by == ObservationTrigger.ON_DEMAND
        assert observation.lens_snapshot["name"] == lens.name
        assert observation.lens_snapshot["lens_type"] == str(lens.lens_type)
        assert observation.lens_snapshot["lens_version"] == lens.lens_version
        assert observation.lens_snapshot["model"] == str(lens.model)
        assert observation.lens_snapshot["provider"] == str(lens.provider)
        assert observation.lens_snapshot["emits_signals"] == lens.emits_signals
        assert observation.lens_snapshot["lens_config"] == lens.lens_config
        assert observation.started_at is None  # set when transitioning to running, not here
        assert observation.completed_at is None

    def test_snapshot_is_frozen_against_later_lens_edits(self) -> None:
        lens = _make_lens()
        original_config = dict(lens.lens_config)
        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.SCHEDULE,
                triggered_by_user_id=None,
                workflow_id="wf-1",
            )
        )

        lens.lens_config = {"prompt": "completely different prompt"}
        lens.save()

        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.lens_snapshot["lens_config"] == original_config

    def test_returns_existing_observation_on_unique_conflict(self) -> None:
        lens = _make_lens()
        existing = _make_observation(lens, session_id="sess-dup")

        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-dup",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-second",
            )
        )

        assert result == CreateObservationOutput(observation_id=existing.id, was_created=False)
        # The original row wasn't touched.
        existing.refresh_from_db()
        assert existing.workflow_id != "wf-second"

    def test_propagates_non_unique_integrity_errors(self) -> None:
        # FK/CHECK violations must surface as activity failures, not silently fall into the dedup path.
        lens = _make_lens()
        fk_error = IntegrityError("insert or update on table violates foreign key constraint")
        fk_error.__cause__ = psycopg.errors.ForeignKeyViolation("violation")

        with patch.object(ReplayObservation.objects, "create", side_effect=fk_error):
            with pytest.raises(IntegrityError):
                create_observation_activity(
                    CreateObservationInputs(
                        lens_id=lens.id,
                        team_id=lens.team_id,
                        session_id="sess-fk",
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                        workflow_id="wf-fk",
                    )
                )

        assert not ReplayObservation.objects.filter(lens=lens, session_id="sess-fk").exists()

    @pytest.mark.parametrize(
        "use_real_lens_id, team_id_offset",
        [
            pytest.param(False, 0, id="lens_does_not_exist"),
            pytest.param(True, 999, id="lens_belongs_to_other_team"),
        ],
    )
    def test_raises_when_lens_not_found_for_team(self, use_real_lens_id: bool, team_id_offset: int) -> None:
        lens = _make_lens()
        lens_id = lens.id if use_real_lens_id else uuid.uuid4()
        team_id = lens.team_id + team_id_offset

        with pytest.raises(ValueError):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=lens_id,
                    team_id=team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                    workflow_id="wf-1",
                )
            )

    def test_raises_when_user_is_not_in_lens_organization(self) -> None:
        lens = _make_lens()
        outsider_org = Organization.objects.create(name="other-org")
        outsider = User.objects.create_and_join(organization=outsider_org, email="x@x.com", password=None)

        with pytest.raises(ValueError, match="not a member"):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=lens.id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=outsider.id,
                    workflow_id="wf-1",
                )
            )

    def test_accepts_user_in_lens_organization(self) -> None:
        lens = _make_lens()
        member = User.objects.create_and_join(organization=lens.team.organization, email="m@m.com", password=None)

        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=member.id,
                workflow_id="wf-1",
            )
        )
        assert result.was_created is True


@pytest.mark.django_db(transaction=True)
class TestObservationStateActivities:
    def test_mark_running_stamps_started_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens, workflow_id="wf-1")
        assert observation.status == ObservationStatus.PENDING

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.RUNNING
        assert observation.workflow_id == "wf-1"
        assert observation.started_at is not None

    def test_mark_failed_records_reason_and_completed_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = ObservationStatus.RUNNING
        observation.started_at = timezone.now()
        observation.save(update_fields=["status", "started_at"])

        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="bad output")
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.error_reason == "bad output"
        assert observation.completed_at is not None

    @pytest.mark.parametrize("terminal_status", [ObservationStatus.SUCCEEDED, ObservationStatus.FAILED])
    def test_terminal_status_is_not_overwritten_by_state_activities(self, terminal_status: str) -> None:
        # Bounded UPDATE protects against retries that race past a settled row.
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = terminal_status
        observation.completed_at = timezone.now()
        observation.error_reason = "original"
        observation.save(update_fields=["status", "completed_at", "error_reason"])

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="late failure")
        )

        observation.refresh_from_db()
        assert observation.status == terminal_status
        assert observation.error_reason == "original"

    def test_mark_running_is_idempotent_against_already_running_rows(self) -> None:
        # `started_at` must survive at-least-once retries; duration metrics depend on it.
        lens = _make_lens()
        observation = _make_observation(lens)
        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        first_started_at = observation.started_at
        assert first_started_at is not None

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        assert observation.started_at == first_started_at

    def test_mark_succeeded_stamps_lifecycle_metadata_and_persists_result(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens, status=ObservationStatus.RUNNING, started_at=timezone.now())
        result = LensResult(model_output=MonitorOutput(verdict=True, reasoning="ok", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(observation_id=observation.id, lens_result=result)
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.SUCCEEDED
        assert observation.completed_at is not None
        assert observation.lens_result == result.model_dump(mode="json")

    def test_mark_succeeded_does_not_overwrite_terminal_status(self) -> None:
        # Bounded UPDATE: failed/succeeded rows are sticky.
        lens = _make_lens()
        observation = _make_observation(
            lens, status=ObservationStatus.FAILED, error_reason="prior", completed_at=timezone.now()
        )
        result = LensResult(model_output=MonitorOutput(verdict=True, reasoning="late", confidence=0.9))

        mark_observation_succeeded_activity(
            MarkObservationSucceededInputs(observation_id=observation.id, lens_result=result)
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.completed_at is not None
        assert observation.lens_result == {}  # not overwritten


@pytest.mark.django_db(transaction=True)
class TestFetchSessionEventsActivity:
    def _make_session_replay_events_mock(
        self,
        metadata: dict | None,
        pages: list[tuple[list[str] | None, list[tuple] | None]],
    ) -> MagicMock:
        mock_obj = MagicMock(spec=SessionReplayEvents)
        mock_obj.get_metadata.return_value = metadata
        mock_obj.get_events.side_effect = pages
        return mock_obj

    @pytest.mark.asyncio
    async def test_stashes_lens_llm_inputs_in_redis(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        end = dt.datetime(2026, 5, 12, 10, 5, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": end, "duration": 300, "active_seconds": 200}

        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [(["event", "timestamp", "$session_id"], [("$pageview", start, "sess-1")])],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                )
            )

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=LensLlmInputs)
        assert stored is not None
        assert stored.session_id == "sess-1"
        assert stored.team_id == lens.team_id
        assert stored.events.columns == ["event", "timestamp", "$session_id"]
        assert stored.session_start_time == start
        assert stored.session_end_time == end
        assert stored.duration_seconds == 300.0
        assert stored.events.rows == [["$pageview", "2026-05-12T10:00:00Z", "sess-1"]]

    @pytest.mark.asyncio
    async def test_paginates_through_get_events_until_short_page(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": start, "duration": 0, "active_seconds": 0}
        page_size = 3000

        full_page_rows = [("$pageview", start, f"sess-{i}") for i in range(page_size)]
        last_page_rows = [("$pageview", start, "sess-last")]
        mock_obj = self._make_session_replay_events_mock(
            metadata,
            [
                (["event", "timestamp", "$session_id"], full_page_rows),
                (["event", "timestamp", "$session_id"], last_page_rows),
            ],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                )
            )

        assert mock_obj.get_events.call_count == 2
        assert mock_obj.get_events.call_args_list[0].kwargs["page"] == 0
        assert mock_obj.get_events.call_args_list[1].kwargs["page"] == 1
        assert mock_obj.get_events.call_args_list[0].kwargs["limit"] == page_size

        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=LensLlmInputs)
        assert stored is not None
        assert len(stored.events.rows) == page_size + 1

    @pytest.mark.asyncio
    async def test_is_idempotent_when_redis_already_has_payload(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        # Pre-populate Redis as if a previous run had finished.
        redis_client = get_async_client(settings.REPLAY_VISION_REDIS_URL)
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        existing = LensLlmInputs(
            session_id="sess-1",
            team_id=lens.team_id,
            session_start_time=dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC),
            session_end_time=dt.datetime(2026, 5, 12, 10, 5, 0, tzinfo=dt.UTC),
            duration_seconds=300.0,
            events=EventTable(columns=["event"], rows=[["$pageview"]]),
        )
        await store_data_in_redis(redis_client, key, existing.model_dump_json())

        mock_obj = MagicMock(spec=SessionReplayEvents)
        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                )
            )

        mock_obj.get_metadata.assert_not_called()
        mock_obj.get_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_session_active_seconds_exceeds_max(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        metadata = {
            "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 5, 12, 2, tzinfo=dt.UTC),
            "duration": 7200,
            "active_seconds": 5000,  # over the 3600 cap
        }
        mock_obj = self._make_session_replay_events_mock(metadata, [(["event"], [("$pageview",)])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id, team_id=lens.team_id, session_id="sess-long"
                    )
                )
            assert exc_info.value.non_retryable is True
            assert "5000" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_session_has_no_events(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        metadata = {
            "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 5, 12, 0, 5, tzinfo=dt.UTC),
            "duration": 300,
            "active_seconds": 200,
        }
        mock_obj = self._make_session_replay_events_mock(metadata, [([], [])])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id,
                        team_id=lens.team_id,
                        session_id="sess-empty",
                    )
                )
            assert exc_info.value.non_retryable is True


@pytest.mark.django_db(transaction=True)
class TestEnsureSessionAssetActivity:
    @pytest.mark.asyncio
    async def test_creates_new_asset_with_vision_render_params(self) -> None:
        lens = await sync_to_async(_make_lens)()
        result = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-fresh")
        )
        assert isinstance(result, EnsureSessionAssetOutput)

        asset = await ExportedAsset.objects.aget(pk=result.asset_id)
        assert asset.team_id == lens.team_id
        assert asset.export_format == "video/mp4"
        assert asset.is_system is True
        ctx = asset.export_context or {}
        assert ctx["session_recording_id"] == "sess-fresh"
        assert ctx["playback_speed"] == 8
        assert ctx["recording_fps"] == 3
        assert ctx["show_metadata_footer"] is True

    @pytest.mark.asyncio
    async def test_reuses_existing_system_asset_for_same_session(self) -> None:
        lens = await sync_to_async(_make_lens)()
        first = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-reuse")
        )
        second = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-reuse")
        )
        assert first.asset_id == second.asset_id

        @sync_to_async
        def _count() -> int:
            return ExportedAsset.objects.filter(
                team_id=lens.team_id, export_context__session_recording_id="sess-reuse"
            ).count()

        assert await _count() == 1

    @pytest.mark.asyncio
    async def test_reuse_does_not_mutate_existing_asset(self) -> None:
        lens = await sync_to_async(_make_lens)()
        first = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-immutable")
        )

        # Simulate a previous rasterize run writing output fields onto the asset.
        @sync_to_async
        def _stamp_output() -> None:
            asset = ExportedAsset.objects.get(pk=first.asset_id)
            ctx = dict(asset.export_context or {})
            ctx["render_fingerprint"] = "abcdef"
            ctx["content_location"] = "s3://prior/video.mp4"
            asset.export_context = ctx
            asset.save(update_fields=["export_context"])

        await _stamp_output()

        await ensure_session_asset_activity(EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-immutable"))

        asset = await ExportedAsset.objects.aget(pk=first.asset_id)
        ctx = asset.export_context or {}
        assert ctx["render_fingerprint"] == "abcdef"
        assert ctx["content_location"] == "s3://prior/video.mp4"


def _build_inputs(**overrides: Any) -> ApplyLensInputs:
    defaults: dict[str, Any] = {
        "lens_id": uuid.uuid4(),
        "session_id": "sess-1",
        "team_id": 1,
        "triggered_by": ObservationTrigger.ON_DEMAND,
        "triggered_by_user_id": None,
    }
    defaults.update(overrides)
    return ApplyLensInputs(**defaults)


class _WorkflowMocks:
    """Tracks `wf.execute_activity` and `wf.execute_child_workflow` calls and dispatches return values per activity."""

    def __init__(
        self,
        *,
        activity_results: dict[Any, Any] | None = None,
        activity_errors: dict[Any, Exception] | None = None,
    ) -> None:
        self.activity_results = activity_results or {}
        self.activity_errors = activity_errors or {}
        self.activity_calls: list[tuple[Any, Any]] = []
        self.child_calls: list[tuple[tuple, dict]] = []

    async def execute_activity(self, activity_fn: Any, activity_input: Any, **_: Any) -> Any:
        self.activity_calls.append((activity_fn, activity_input))
        if activity_fn in self.activity_errors:
            raise self.activity_errors[activity_fn]
        return self.activity_results.get(activity_fn)

    async def execute_child_workflow(self, *args: Any, **kwargs: Any) -> Any:
        self.child_calls.append((args, kwargs))
        return None


async def _run_workflow(inputs: ApplyLensInputs, mocks: _WorkflowMocks, workflow_id: str = "wf-test") -> None:
    workflow_info = MagicMock()
    workflow_info.workflow_id = workflow_id
    with (
        patch("temporalio.workflow.info", return_value=workflow_info),
        patch("temporalio.workflow.execute_activity", side_effect=mocks.execute_activity),
        patch("temporalio.workflow.execute_child_workflow", side_effect=mocks.execute_child_workflow),
    ):
        await ApplyLensWorkflow().run(inputs)


@pytest.mark.asyncio
async def test_apply_lens_workflow_drives_full_success_pipeline() -> None:
    new_observation_id = uuid.uuid4()
    model_output = MonitorOutput(verdict=True, reasoning="user exported", confidence=0.9)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_lens_provider_activity: LensCallOutput(model_output=model_output),
        },
    )

    inputs = _build_inputs(session_id="sess-1", team_id=99)
    await _run_workflow(inputs, mocks, workflow_id="wf-success")

    activity_order = [fn for fn, _ in mocks.activity_calls]
    assert activity_order[:2] == [create_observation_activity, mark_observation_running_activity]
    # fetch + ensure_asset run in parallel — order between them is non-deterministic.
    assert set(activity_order[2:4]) == {fetch_session_events_activity, ensure_session_asset_activity}
    assert activity_order[4:] == [
        upload_video_to_gemini_activity,
        call_lens_provider_activity,
        emit_observation_event_activity,
        mark_observation_succeeded_activity,
        cleanup_gemini_file_activity,
    ]
    assert len(mocks.child_calls) == 1
    assert mocks.child_calls[0][1]["id"] == f"replay-vision-rasterize-99-sess-1-{inputs.lens_id}"

    emit_input = next(arg for fn, arg in mocks.activity_calls if fn is emit_observation_event_activity)
    assert emit_input.model_output == model_output
    cleanup_input = next(arg for fn, arg in mocks.activity_calls if fn is cleanup_gemini_file_activity)
    assert cleanup_input.gemini_file_name == "files/x"


@pytest.mark.asyncio
async def test_apply_lens_workflow_marks_failed_when_fetch_raises() -> None:
    new_observation_id = uuid.uuid4()
    fetch_error = ApplicationError("no events", non_retryable=True)
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
        },
        activity_errors={fetch_session_events_activity: fetch_error},
    )

    with pytest.raises(ApplicationError, match="no events"):
        await _run_workflow(_build_inputs(session_id="sess-broken"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert create_observation_activity in called
    assert mark_observation_running_activity in called
    assert fetch_session_events_activity in called
    assert mark_observation_failed_activity in called
    assert mocks.child_calls == []

    failed_input = mocks.activity_calls[-1][1]
    assert failed_input.observation_id == new_observation_id
    assert "no events" in failed_input.error_reason.lower()


@pytest.mark.asyncio
async def test_apply_lens_workflow_cleans_up_gemini_file_when_call_provider_fails() -> None:
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
        },
        activity_errors={call_lens_provider_activity: ApplicationError("model rejected", non_retryable=True)},
    )

    with pytest.raises(ApplicationError, match="model rejected"):
        await _run_workflow(_build_inputs(session_id="sess-bad"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert upload_video_to_gemini_activity in called
    assert call_lens_provider_activity in called
    assert cleanup_gemini_file_activity in called  # cleanup ran despite call_provider raising
    assert mark_observation_failed_activity in called
    # mark_succeeded must NOT have been called
    assert mark_observation_succeeded_activity not in called


@pytest.mark.asyncio
async def test_apply_lens_workflow_succeeds_even_when_cleanup_fails() -> None:
    # Cleanup is best-effort; a cleanup failure must not bring down an already-succeeded workflow.
    new_observation_id = uuid.uuid4()
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=new_observation_id, was_created=True),
            ensure_session_asset_activity: EnsureSessionAssetOutput(asset_id=42),
            upload_video_to_gemini_activity: UploadedVideo(
                file_uri="gemini://files/x", mime_type="video/mp4", gemini_file_name="files/x"
            ),
            call_lens_provider_activity: LensCallOutput(
                model_output=MonitorOutput(verdict=True, reasoning="ok", confidence=0.9),
            ),
        },
        activity_errors={cleanup_gemini_file_activity: RuntimeError("cleanup failed")},
    )

    # Workflow should complete without raising despite cleanup failure.
    await _run_workflow(_build_inputs(session_id="sess-ok"), mocks)

    called = {fn for fn, _ in mocks.activity_calls}
    assert mark_observation_succeeded_activity in called
    assert emit_observation_event_activity in called
    assert cleanup_gemini_file_activity in called


@pytest.mark.asyncio
async def test_apply_lens_workflow_exits_when_create_returns_was_created_false() -> None:
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=uuid.uuid4(), was_created=False),
        },
    )

    await _run_workflow(_build_inputs(session_id="sess-dup"), mocks)

    assert [fn for fn, _ in mocks.activity_calls] == [create_observation_activity]
    assert mocks.child_calls == []


@pytest.mark.asyncio
async def test_apply_lens_workflow_propagates_workflow_id_to_create() -> None:
    mocks = _WorkflowMocks(
        activity_results={
            create_observation_activity: CreateObservationOutput(observation_id=uuid.uuid4(), was_created=False),
        },
    )
    inputs = _build_inputs(
        lens_id=uuid.uuid4(),
        session_id="sess-id",
        team_id=7,
        triggered_by=ObservationTrigger.SCHEDULE,
        triggered_by_user_id=42,
    )

    await _run_workflow(inputs, mocks, workflow_id="wf-from-info")

    create_input = mocks.activity_calls[0][1]
    assert create_input.lens_id == inputs.lens_id
    assert create_input.session_id == "sess-id"
    assert create_input.team_id == 7
    assert create_input.triggered_by == ObservationTrigger.SCHEDULE
    assert create_input.triggered_by_user_id == 42
    assert create_input.workflow_id == "wf-from-info"
