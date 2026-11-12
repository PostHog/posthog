from collections.abc import Iterable
from typing import Any

from django.core.management.base import CommandParser, OutputWrapper

from posthog.dataclasses import frozen

NIL_UUID = "00000000-0000-0000-0000-000000000000"
MAX_BATCH_SIZE = 5000


@frozen
class BackfillBatch:
    tasks: int
    cursor: str


def add_backfill_arguments(parser: CommandParser) -> None:
    parser.add_argument("--team-id", type=int, metavar="ID", help="Only tasks in this team")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--after", help="Resume after this task id, as printed by an earlier run")
    parser.add_argument("--sleep-seconds", type=float, default=0.1, help="Pause between batches")
    parser.add_argument("--dry-run", action="store_true", help="Count the tasks without writing")


def backfill_options(options: dict[str, Any]) -> dict[str, Any]:
    return {key: options[key] for key in ("team_id", "batch_size", "after", "dry_run", "sleep_seconds")}


def report_backfill(stdout: OutputWrapper, batches: Iterable[BackfillBatch], *, dry_run: bool) -> None:
    verb = "Would fill" if dry_run else "Filled"
    total = 0
    for batch in batches:
        total += batch.tasks
        stdout.write(f"{verb} {total} tasks; resume after {batch.cursor}")
    stdout.write(f"{verb} {total} tasks in all")
