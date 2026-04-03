import os
import time
import datetime as dt

from django.core.management.base import BaseCommand

from posthog.models import Team, User
from posthog.models.exported_asset import ExportedAsset, get_public_access_token
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.tasks.exports.video_exporter import RecordReplayToFileOptions, record_replay_to_file
from posthog.utils import absolute_uri


class Command(BaseCommand):
    help = "Test local video export. Requires a running local PostHog dev server."

    def add_arguments(self, parser):
        parser.add_argument("--session-id", type=str, default="019c90da-973b-70c1-9be7-08cb8c6da571")
        parser.add_argument("--team-id", type=int, default=1)
        parser.add_argument("--playback-speed", type=int, default=8)
        parser.add_argument("--recording-fps", type=int, default=3)

    def handle(self, *args, **options):
        team_id = options["team_id"]
        session_id = options["session_id"]
        playback_speed = options["playback_speed"]
        recording_fps = options["recording_fps"]

        team = Team.objects.get(id=team_id)
        metadata = SessionReplayEvents().get_metadata(session_id=session_id, team=team)
        if not metadata:
            self.stderr.write(self.style.ERROR(f"No metadata found for session {session_id}"))
            return
        duration = int(metadata["duration"])

        self.stdout.write(f"Team ID: {team_id}")
        self.stdout.write(f"Session ID: {session_id}")
        self.stdout.write(f"Duration: {duration}s (from session metadata)")
        self.stdout.write(f"Playback speed: {playback_speed}x")
        self.stdout.write(f"Recording FPS: {recording_fps}")

        user = User.objects.first()
        if not user:
            self.stderr.write(self.style.WARNING("No user found, export token will be empty (API calls will fail)"))

        asset = ExportedAsset.objects.create(
            team_id=team_id,
            export_format="video/mp4",
            created_by=user,
            export_context={
                "session_recording_id": session_id,
                "timestamp": 0,
                "duration": duration,
                "playback_speed": playback_speed,
                "recording_fps": recording_fps,
                "mode": "video",
                "show_metadata_footer": True,
            },
        )
        self.stdout.write(f"Created ExportedAsset ID: {asset.id}")

        access_token = get_public_access_token(asset, dt.timedelta(minutes=60))

        url_params = {
            "token": access_token,
            "t": 0,
            "fullscreen": "true",
            "inspectorSideBar": "false",
            "showInspector": "false",
            "playerSpeed": playback_speed,
            "showMetadataFooter": "true",
        }
        url = absolute_uri(f"/exporter?{'&'.join(f'{key}={value}' for key, value in url_params.items())}")

        output_path = os.path.join(os.getcwd(), f"test_export_{session_id}_{playback_speed}x.mp4")
        self.stdout.write(f"URL: {url}")
        self.stdout.write(f"Output: {output_path}")
        self.stdout.write("")

        os.environ["EXPORTER_HEADLESS"] = "0"

        start = time.monotonic()
        inactivity_periods = record_replay_to_file(
            RecordReplayToFileOptions(
                image_path=output_path,
                url_to_render=url,
                wait_for_css_selector=".replayer-wrapper",
                recording_duration=duration,
                playback_speed=playback_speed,
                use_puppeteer=True,
                recording_fps=recording_fps,
            ),
        )
        elapsed = time.monotonic() - start

        self.stdout.write(self.style.SUCCESS(f"\nExport completed in {elapsed:.1f}s"))
        self.stdout.write(f"Output file: {output_path}")
        if os.path.exists(output_path):
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            self.stdout.write(f"File size: {size_mb:.1f} MB")
        if inactivity_periods:
            active = sum(1 for p in inactivity_periods if p.active)
            self.stdout.write(f"Inactivity periods: {len(inactivity_periods)} ({active} active)")
