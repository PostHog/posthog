"""Remove code variables from the stored error tracking stack frames of one team.

Run this command after every cymbal processing pod runs with the team in
`ERROR_TRACKING_DROP_CODE_VARIABLES_TEAM_IDS`. Cymbal reads that list at startup, so a pod from
before the rollout can resolve a frame again from an incoming event and write the variables back
behind the backfill cursor. After the live run, a dry run reports `matched=0` when no frame of the
team keeps code variables.

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
from django.db.models import F, Func, JSONField, QuerySet, TextField, Value

import structlog

from products.error_tracking.backend.models import ErrorTrackingStackFrame

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 1_000
CODE_VARIABLES_KEY = "code_variables"


# nosemgrep: python.django.security.audit.extends-custom-expression.extends-custom-expression
class JSONBRemoveKey(Func):
    """Postgres `jsonb - text`, which returns the JSON object without that key.

    The template and the joiner are fixed. Callers pass a column and a `Value`, which Django sends as a
    query parameter, so no caller-supplied text reaches the SQL.
    """

    template = "%(expressions)s"
    arg_joiner = " - "
    output_field = JSONField()


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

        scanned_total = 0
        matched_total = 0
        updated_total = 0
        cursor = start_after_raw_id
        while raw_ids := self._get_raw_ids(team_id=team_id, after_raw_id=cursor, batch_size=batch_size):
            cursor = raw_ids[-1]
            scanned_total += len(raw_ids)
            frames = self._frames_with_code_variables(team_id=team_id, raw_ids=raw_ids)
            if live_run:
                updated = self._drop_code_variables(frames)
                matched_total += updated
                updated_total += updated
            else:
                matched_total += frames.count()

            logger.info(
                "stack_frame_code_variables_drop_progress",
                team_id=team_id,
                scanned=scanned_total,
                matched=matched_total,
                updated=updated_total,
                last_raw_id=cursor,
            )

        logger.info(
            "stack_frame_code_variables_drop_complete",
            team_id=team_id,
            scanned=scanned_total,
            matched=matched_total,
            updated=updated_total,
            last_raw_id=cursor,
        )

    def _get_raw_ids(self, *, team_id: int, after_raw_id: str | None, batch_size: int) -> list[str]:
        # Page over every raw_id of the team, so that each batch is a range scan on the
        # (team_id, raw_id, part) unique index and every part of a raw frame lands in the same batch.
        # Do not add the jsonb filter here: with it, the planner can rescan all remaining team rows for each batch.
        raw_ids = ErrorTrackingStackFrame.objects.filter(team_id=team_id)
        if after_raw_id is not None:
            raw_ids = raw_ids.filter(raw_id__gt=after_raw_id)

        return list(raw_ids.order_by("raw_id").values_list("raw_id", flat=True).distinct()[:batch_size])

    def _frames_with_code_variables(self, *, team_id: int, raw_ids: list[str]) -> QuerySet[ErrorTrackingStackFrame]:
        return ErrorTrackingStackFrame.objects.filter(
            team_id=team_id, raw_id__in=raw_ids, contents__has_key=CODE_VARIABLES_KEY
        )

    def _drop_code_variables(self, frames: QuerySet[ErrorTrackingStackFrame]) -> int:
        # Postgres removes the key in one UPDATE. The statement never carries frame contents, and it
        # cannot write stale contents over a concurrent cymbal upsert of the same row.
        return frames.update(
            contents=JSONBRemoveKey(F("contents"), Value(CODE_VARIABLES_KEY, output_field=TextField()))
        )
