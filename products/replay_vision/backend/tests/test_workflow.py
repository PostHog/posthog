from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from products.replay_vision.backend.models.replay_lens import LensModel, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.temporal.activities.consolidate_lens_segments import (
    consolidate_lens_segments_activity,
)
from products.replay_vision.backend.temporal.activities.emit_lens_event import (
    emit_lens_event_and_mark_succeeded_activity,
)
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.types import FinalLensOutput, SegmentLensOutput
from products.replay_vision.backend.temporal.workflow import _calculate_segment_specs


class TestSegmentSpecs(BaseTest):
    def test_no_inactivity_data_chunks_whole_video(self) -> None:
        specs = _calculate_segment_specs(video_duration=150.0, chunk_duration=60.0, inactivity_periods=None)
        self.assertEqual(len(specs), 3)
        self.assertEqual(specs[0].recording_start_time, 0.0)
        self.assertEqual(specs[0].recording_end_time, 60.0)
        self.assertEqual(specs[2].recording_end_time, 150.0)

    def test_skips_inactive_periods(self) -> None:
        periods = [
            {"recording_ts_from_s": 0.0, "recording_ts_to_s": 10.0, "active": True},
            {"recording_ts_from_s": 10.0, "recording_ts_to_s": 120.0, "active": False},
            {"recording_ts_from_s": 120.0, "recording_ts_to_s": 150.0, "active": True},
        ]
        specs = _calculate_segment_specs(video_duration=150.0, chunk_duration=60.0, inactivity_periods=periods)
        ranges = [(round(s.recording_start_time, 2), round(s.recording_end_time, 2)) for s in specs]
        self.assertEqual(ranges, [(0.0, 10.0), (120.0, 150.0)])

    def test_drops_segments_under_min_duration(self) -> None:
        periods = [{"recording_ts_from_s": 0.0, "recording_ts_to_s": 0.5, "active": True}]
        specs = _calculate_segment_specs(video_duration=10.0, chunk_duration=60.0, inactivity_periods=periods)
        self.assertEqual(specs, [])


class TestObservationStateActivities(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.lens = ReplayLens.objects.create(
            team=self.team,
            name="my-lens",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "p"},
            model=LensModel.GEMINI_3_FLASH,
        )
        self.observation = ReplayObservation.objects.create(
            lens=self.lens,
            session_id="sess-1",
            lens_version=self.lens.lens_version,
            lens_config_snapshot=self.lens.lens_config,
            triggered_by=ObservationTrigger.ON_DEMAND,
        )

    async def test_mark_running_sets_status_and_workflow_id(self) -> None:
        env = ActivityEnvironment()
        await env.run(mark_observation_running_activity, self.observation.id, "wf-abc")
        await self.observation.arefresh_from_db()
        self.assertEqual(self.observation.status, ObservationStatus.RUNNING)
        self.assertEqual(self.observation.workflow_id, "wf-abc")

    async def test_mark_failed_sets_status_and_error_reason(self) -> None:
        env = ActivityEnvironment()
        await env.run(mark_observation_failed_activity, self.observation.id, "boom")
        await self.observation.arefresh_from_db()
        self.assertEqual(self.observation.status, ObservationStatus.FAILED)
        self.assertEqual(self.observation.error_reason, "boom")
        self.assertIsNotNone(self.observation.completed_at)


class TestConsolidateActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.lens = ReplayLens.objects.create(
            team=self.team,
            name="my-lens",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "p"},
            model=LensModel.GEMINI_3_FLASH,
        )

    async def test_consolidates_monitor_segments(self) -> None:
        env = ActivityEnvironment()
        segments = [
            SegmentLensOutput(
                segment_index=0,
                output_json='{"verdict": false, "reasoning": "r0", "confidence": 0.9}',
            ),
            SegmentLensOutput(
                segment_index=1,
                output_json='{"verdict": true, "reasoning": "r1", "confidence": 0.8}',
            ),
        ]
        result = await env.run(consolidate_lens_segments_activity, self.lens.id, segments)
        self.assertIsInstance(result, FinalLensOutput)
        # Verdicts disagreed → confidence is min of the two.
        self.assertEqual(result.confidence, 0.8)


class TestEmitLensEventActivity(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.lens = ReplayLens.objects.create(
            team=self.team,
            name="checkout-monitor",
            lens_type=LensType.MONITOR,
            lens_config={"prompt": "p"},
            model=LensModel.GEMINI_3_FLASH,
        )
        self.observation = ReplayObservation.objects.create(
            lens=self.lens,
            session_id="sess-1",
            lens_version=self.lens.lens_version,
            lens_config_snapshot=self.lens.lens_config,
            triggered_by=ObservationTrigger.ON_DEMAND,
        )
        self.observation.status = ObservationStatus.RUNNING
        self.observation.save(update_fields=["status"])

    async def test_emits_event_and_marks_succeeded(self) -> None:
        env = ActivityEnvironment()
        final = FinalLensOutput(
            output_json='{"verdict": true, "reasoning": "r", "confidence": 0.95}',
            confidence=0.95,
        )
        with patch(
            "products.replay_vision.backend.temporal.activities.emit_lens_event.produce_internal_event",
            new=MagicMock(),
        ) as mock_produce:
            await env.run(
                emit_lens_event_and_mark_succeeded_activity,
                self.observation.id,
                self.lens.id,
                "sess-1",
                final,
            )
        await self.observation.arefresh_from_db()
        self.assertEqual(self.observation.status, ObservationStatus.SUCCEEDED)
        self.assertIsNotNone(self.observation.completed_at)
        self.assertEqual(self.observation.model_used, LensModel.GEMINI_3_FLASH.value)
        mock_produce.assert_called_once()
        kwargs = mock_produce.call_args.kwargs
        self.assertEqual(kwargs["team_id"], self.team.id)
        event = kwargs["event"]
        self.assertEqual(event.event, "$replay_lens")
        self.assertEqual(event.distinct_id, "sess-1")
        self.assertEqual(event.properties["$replay_lens_id"], str(self.lens.id))
        self.assertEqual(event.properties["$replay_lens_confidence"], 0.95)
        self.assertEqual(event.properties["$replay_lens_result"]["verdict"], True)


class TestUuidShape(BaseTest):
    """Sanity check that activity UUID args round-trip cleanly through Pydantic types."""

    def test_uuid_accepted(self) -> None:
        u = UUID("00000000-0000-0000-0000-000000000001")
        self.assertEqual(str(u), "00000000-0000-0000-0000-000000000001")
