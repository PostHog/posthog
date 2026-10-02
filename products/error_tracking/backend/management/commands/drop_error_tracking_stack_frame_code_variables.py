"""Remove code variables from the stored error tracking stack frames of one team.

Run this command after cymbal drops code variables for the team through
`ERROR_TRACKING_DROP_CODE_VARIABLES_TEAM_IDS`. Before that, cymbal can resolve a frame again from
an incoming event and write the variables back behind the backfill cursor.

Usage:
    python manage.py drop_error_tracking_stack_frame_code_variables --team-id 2
    python manage.py drop_error_tracking_stack_frame_code_variables --team-id 2 --live-run
    python manage.py drop_error_tracking_stack_frame_code_variables --team-id 2 --live-run --batch-size 500
    python manage.py drop_error_tracking_stack_frame_code_variables --team-id 2 --live-run --start-after-raw-id <raw-id>
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet

import structlog

from products.error_tracking.backend.models import ErrorTrackingStackFrame

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 1_000
CODE_VARIABLES_KEY = "code_variables"


class Command(BaseCommand):
    help = "Remove code variables from the stored error tracking stack frames of one team."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Remove code variables from the stack frames of this team.",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="Update stored stack frames. The default is a dry run.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Number of matching raw frames to process per transaction. The default is {DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--start-after-raw-id",
            type=str,
            default=None,
            help="Resume after this raw frame id.",
        )

    def handle(
        self,
        *,
        team_id: int,
        live_run: bool,
        batch_size: int,
        start_after_raw_id: str | None,
        **options: object,
    ) -> None:
        logger.setLevel(logging.INFO)
        if batch_size <= 0:
            raise CommandError("Batch size must be greater than zero.")

        mode = "LIVE" if live_run else "DRY-RUN"
        logger.info(
            "stack_frame_code_variables_drop_starting",
            mode=mode,
            team_id=team_id,
            batch_size=batch_size,
            start_after_raw_id=start_after_raw_id,
        )

        matched_total = 0
        updated_total = 0
        cursor = start_after_raw_id
        while candidate_raw_ids := self._get_candidate_raw_ids(
            team_id=team_id, after_raw_id=cursor, batch_size=batch_size
        ):
            cursor = candidate_raw_ids[-1]
            matched_total += len(candidate_raw_ids)
            if live_run:
                updated_total += self._drop_code_variables(team_id=team_id, raw_ids=candidate_raw_ids)

            logger.info(
                "stack_frame_code_variables_drop_progress",
                team_id=team_id,
                matched=matched_total,
                updated=updated_total,
                last_raw_id=cursor,
            )

        logger.info(
            "stack_frame_code_variables_drop_complete",
            team_id=team_id,
            matched=matched_total,
            updated=updated_total,
            last_raw_id=cursor,
        )

    def _get_candidate_raw_ids(self, *, team_id: int, after_raw_id: str | None, batch_size: int) -> list[str]:
        # Page by raw_id, not id, so that the (team_id, raw_id, part) unique index orders the team's
        # frames, and every part of a raw frame lands in the same batch.
        candidates = ErrorTrackingStackFrame.objects.filter(team_id=team_id, contents__has_key=CODE_VARIABLES_KEY)
        if after_raw_id is not None:
            candidates = candidates.filter(raw_id__gt=after_raw_id)

        return list(candidates.order_by("raw_id").values_list("raw_id", flat=True).distinct()[:batch_size])

    def _drop_code_variables(self, *, team_id: int, raw_ids: list[str]) -> int:
        with transaction.atomic():
            frames: QuerySet[ErrorTrackingStackFrame] = ErrorTrackingStackFrame.objects.select_for_update().filter(
                team_id=team_id, raw_id__in=raw_ids, contents__has_key=CODE_VARIABLES_KEY
            )
            frames_to_update: list[ErrorTrackingStackFrame] = []
            for frame in frames.only("id", "contents"):
                del frame.contents[CODE_VARIABLES_KEY]
                frames_to_update.append(frame)

            if frames_to_update:
                ErrorTrackingStackFrame.objects.bulk_update(frames_to_update, ["contents"])
            return len(frames_to_update)
