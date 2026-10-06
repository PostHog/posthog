"""Mask the code variables in the stored error tracking stack frames of the listed teams.

Run this command after every cymbal processing pod masks code variables. Until then, a pod can
resolve a frame again from an incoming event and write unmasked variables back behind the cursor.
After the live run, a dry run reports `matched=0` when no stored frame has variables left to mask.
A second run over the same teams is safe: it reads every frame again but writes nothing new.

Usage:
    python manage.py mask_error_tracking_stack_frame_code_variables --team-ids 7,42
    python manage.py mask_error_tracking_stack_frame_code_variables --team-ids 7,42 --live-run
    python manage.py mask_error_tracking_stack_frame_code_variables --team-ids 7 --live-run --start-after-raw-id <raw-id>
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from typing import TYPE_CHECKING

from django.contrib.postgres.fields import ArrayField
from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Func, JSONField, TextField, Value

import structlog

from products.error_tracking.backend.logic.code_variables_masking import mask_code_variables
from products.error_tracking.backend.models import ErrorTrackingStackFrame

if TYPE_CHECKING:
    from uuid import UUID

    from products.error_tracking.backend.logic.code_variables_masking import JSONValue

logger = structlog.get_logger(__name__)

DEFAULT_BATCH_SIZE = 1_000
CODE_VARIABLES_KEY = "code_variables"


def parse_team_ids(value: str) -> list[int]:
    try:
        team_ids = sorted({int(part) for part in value.split(",") if part.strip()})
    except ValueError as error:
        raise CommandError(f"Team ids must be a comma-separated list of integers, got {value!r}.") from error
    if not team_ids:
        raise CommandError("List at least one team id.")
    return team_ids


class Command(BaseCommand):
    help = "Mask the code variables in the stored error tracking stack frames of the listed teams."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--team-ids",
            type=str,
            required=True,
            help="Comma-separated ids of the teams whose stack frames to mask.",
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
            help=f"Number of raw frames to read per batch. The default is {DEFAULT_BATCH_SIZE}.",
        )
        parser.add_argument(
            "--start-after-raw-id",
            type=str,
            default=None,
            help="Resume after this raw frame id. Only with a single team id.",
        )

    def handle(
        self,
        *,
        team_ids: str,
        live_run: bool,
        batch_size: int,
        start_after_raw_id: str | None,
        **options: object,
    ) -> None:
        logger.setLevel(logging.INFO)
        if batch_size <= 0:
            raise CommandError("Batch size must be greater than zero.")
        listed = parse_team_ids(team_ids)
        if start_after_raw_id is not None and len(listed) > 1:
            raise CommandError("--start-after-raw-id works with a single team id.")

        mode = "LIVE" if live_run else "DRY-RUN"
        logger.info(
            "stack_frame_code_variables_mask_starting",
            mode=mode,
            team_ids=listed,
            batch_size=batch_size,
            start_after_raw_id=start_after_raw_id,
        )

        totals = {"teams": 0, "scanned": 0, "matched": 0, "updated": 0}
        for team_id in listed:
            team_totals = self._mask_team(
                team_id=team_id, live_run=live_run, batch_size=batch_size, after_raw_id=start_after_raw_id
            )
            totals["teams"] += 1
            for key, count in team_totals.items():
                totals[key] += count

        logger.info("stack_frame_code_variables_mask_complete", mode=mode, **totals)

    def _mask_team(self, *, team_id: int, live_run: bool, batch_size: int, after_raw_id: str | None) -> dict[str, int]:
        totals = {"scanned": 0, "matched": 0, "updated": 0}
        cursor = after_raw_id
        while raw_ids := self._get_raw_ids(team_id=team_id, after_raw_id=cursor, batch_size=batch_size):
            cursor = raw_ids[-1]
            totals["scanned"] += len(raw_ids)
            for frame_id, code_variables in self._code_variables(team_id=team_id, raw_ids=raw_ids):
                masked = mask_code_variables(code_variables)
                if masked == code_variables:
                    continue
                totals["matched"] += 1
                if live_run:
                    totals["updated"] += self._write_masked(frame_id=frame_id, original=code_variables, masked=masked)

            logger.info("stack_frame_code_variables_mask_progress", team_id=team_id, last_raw_id=cursor, **totals)

        logger.info("stack_frame_code_variables_mask_team_complete", team_id=team_id, last_raw_id=cursor, **totals)
        return totals

    def _get_raw_ids(self, *, team_id: int, after_raw_id: str | None, batch_size: int) -> list[str]:
        # Page over every raw_id of the team, so that each batch is a range scan on the
        # (team_id, raw_id, part) unique index and every part of a raw frame lands in the same batch.
        # Do not add the jsonb filter here: with it, the planner can rescan all remaining team rows for each batch.
        raw_ids = ErrorTrackingStackFrame.objects.filter(team_id=team_id)
        if after_raw_id is not None:
            raw_ids = raw_ids.filter(raw_id__gt=after_raw_id)

        return list(raw_ids.order_by("raw_id").values_list("raw_id", flat=True).distinct()[:batch_size])

    def _code_variables(self, *, team_id: int, raw_ids: list[str]) -> list[tuple[UUID, JSONValue]]:
        return list(
            ErrorTrackingStackFrame.objects.filter(
                team_id=team_id, raw_id__in=raw_ids, contents__has_key=CODE_VARIABLES_KEY
            ).values_list("id", f"contents__{CODE_VARIABLES_KEY}")
        )

    def _write_masked(self, *, frame_id: UUID, original: JSONValue, masked: JSONValue) -> int:
        # jsonb_set replaces only the code_variables key. The filter on the value that was read skips
        # a row that cymbal rewrote in the meantime, so the command never writes stale contents.
        return ErrorTrackingStackFrame.objects.filter(
            id=frame_id, **{f"contents__{CODE_VARIABLES_KEY}": original}
        ).update(
            contents=Func(
                F("contents"),
                Value([CODE_VARIABLES_KEY], output_field=ArrayField(TextField())),
                Value(masked, output_field=JSONField()),
                function="jsonb_set",
                output_field=JSONField(),
            )
        )
