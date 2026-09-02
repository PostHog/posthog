from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils.timezone import now

from parameterized import parameterized

from posthog.temporal.session_replay.rasterize_recording.types import RASTERIZE_WORKFLOW_TIMEOUT

from products.exports.backend.models.exported_asset import ExportedAsset
from products.exports.backend.stuck_exports import fail_stuck_video_exports
from products.exports.backend.tasks.failure_handler import FAILURE_TYPE_TIMEOUT_GENERATION

_PAST_ENVELOPE = RASTERIZE_WORKFLOW_TIMEOUT + timedelta(minutes=1)


class TestFailStuckVideoExports(APIBaseTest):
    """The workflow records its own failures, but not the ones where it never ran: its execution
    timeout firing, a dispatch failure, a lost worker. This sweep is the only thing that closes those.
    """

    def _create(self, age: timedelta = _PAST_ENVELOPE, **overrides) -> ExportedAsset:
        fields: dict = {
            "team": self.team,
            "export_format": ExportedAsset.ExportFormat.MP4,
            "export_context": {"session_recording_id": "s1"},
            "created_by": self.user,
        }
        fields.update(overrides)
        with freeze_time(now() - age):
            return ExportedAsset.objects.create(**fields)

    def test_fails_a_video_export_whose_workflow_never_reported_back(self) -> None:
        asset = self._create()

        with patch("products.exports.backend.stuck_exports.ph_scoped_capture"):
            self.assertEqual(fail_stuck_video_exports(), 1)

        asset.refresh_from_db()
        self.assertIsNotNone(asset.exception)
        self.assertEqual(asset.exception_type, "WORKFLOW_TIMEOUT")
        self.assertEqual(asset.failure_type, FAILURE_TYPE_TIMEOUT_GENERATION)

    @parameterized.expand(
        [
            # Still inside the envelope, so the render may well be working.
            ("within_envelope", {"age": timedelta(minutes=5)}),
            # Already terminal, so the sweep has nothing to add and must not overwrite the reason.
            ("already_failed", {"exception": "the renderer said why"}),
            ("has_content_location", {"content_location": "exports/mp4/team-1/task-1/v.mp4"}),
            ("has_inline_content", {"content": b"video bytes"}),
            # Rendered by a different pipeline, which answers to a different deadline.
            ("not_a_video_export", {"export_format": ExportedAsset.ExportFormat.PNG}),
            # replay_vision reuses one contentless system row per session across scans, so an old
            # created_at doesn't prove nothing is rendering it right now.
            ("system_render", {"is_system": True}),
        ]
    )
    def test_leaves_other_exports_alone(self, _name, overrides: dict) -> None:
        asset = self._create(**overrides)
        exception_before = asset.exception

        with patch("products.exports.backend.stuck_exports.ph_scoped_capture"):
            self.assertEqual(fail_stuck_video_exports(), 0)

        asset.refresh_from_db()
        self.assertEqual(asset.exception, exception_before)

    def test_reports_each_export_it_fails(self) -> None:
        self._create()
        self._create()

        with patch("products.exports.backend.stuck_exports.capture_export_event") as capture_event:
            with patch("products.exports.backend.stuck_exports.ph_scoped_capture"):
                fail_stuck_video_exports()

        self.assertEqual([call.args[1] for call in capture_event.call_args_list], ["export failed"] * 2)

    def test_does_not_report_the_same_export_twice(self) -> None:
        """Runs hourly, so an export it already failed must drop out of the next sweep."""
        self._create()

        with patch("products.exports.backend.stuck_exports.ph_scoped_capture"):
            self.assertEqual(fail_stuck_video_exports(), 1)
            self.assertEqual(fail_stuck_video_exports(), 0)
