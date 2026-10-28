import asyncio
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser
from django.utils import timezone

from asgiref.sync import async_to_sync, sync_to_async
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.api.scanners import WATCH_FEED_CANDIDATE_CAP, WATCH_FEED_MAX_WINDOW_DAYS
from products.replay_vision.backend.temporal.media_types import (
    MEDIA_WORKFLOW_EXECUTION_TIMEOUT,
    MEDIA_WORKFLOW_NAME,
    ObservationMediaInputs,
    build_media_workflow_id,
)
from products.replay_vision.backend.watch_thumbnail_backfill import (
    teams_scanned_before_thumbnails,
    thumbnail_backfill_targets,
)


class Command(BaseCommand):
    help = "Cut thumbnails for Replay Vision feed picks scanned before observations had one"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, action="append", help="Only this team; repeat for more")
        parser.add_argument(
            "--days", type=int, default=WATCH_FEED_MAX_WINDOW_DAYS, help="The feed window to pick from, in days"
        )
        parser.add_argument(
            "--per-second",
            type=float,
            default=2.0,
            help="Renders started per second, which bounds the load on the shared rasterization queue",
        )
        parser.add_argument("--dry-run", action="store_true", help="Count what would be rendered, start nothing")

    def handle(self, *args: Any, **options: Any) -> None:
        async_to_sync(self._backfill)(options)

    async def _backfill(self, options: dict[str, Any]) -> None:
        now = timezone.now()
        since = now - timedelta(days=options["days"])
        team_ids = options["team_id"] or await sync_to_async(teams_scanned_before_thumbnails)(since)
        client = None if options["dry_run"] else await async_connect()
        picks = started = without_video = 0
        for team_id in team_ids:
            try:
                targets = await sync_to_async(thumbnail_backfill_targets)(team_id, since, now, WATCH_FEED_CANDIDATE_CAP)
                team_started = await _start_renders(client, targets.renders, options["per_second"]) if client else 0
            except Exception as e:
                # One team's slow query or a Temporal hiccup must not stop the rest.
                self.stderr.write(f"Team {team_id}: skipped ({e.__class__.__name__}: {e})")
                continue
            picks += targets.picks
            started += team_started
            without_video += targets.without_video
            self.stdout.write(
                f"Team {team_id}: {targets.picks} picks, {len(targets.renders)} need a thumbnail, "
                f"{targets.without_video} have no video left, {team_started} renders started."
            )
        self.stdout.write(f"Done: {picks} picks, {started} renders started, {without_video} without a video.")


async def _start_renders(client: Client, renders: list[ObservationMediaInputs], per_second: float) -> int:
    started = 0
    for inputs in renders:
        try:
            # The same start the scan makes, so a render already running for an observation keeps its id.
            await client.start_workflow(
                MEDIA_WORKFLOW_NAME,
                inputs,
                id=build_media_workflow_id(inputs.observation_id),
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                retry_policy=RetryPolicy(maximum_attempts=1),
                execution_timeout=MEDIA_WORKFLOW_EXECUTION_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            continue
        started += 1
        await asyncio.sleep(1 / per_second)
    return started
