from pathlib import Path
from typing import Any
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from products.logs.backend.platform_alert_backfill import (
    backfill_platform_alert_configurations,
    disable_platform_alert_configurations,
)


class Command(BaseCommand):
    help = "Copy logs alert configurations into the skeleton shared alert tables."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Copy one team's configurations only.")
        parser.add_argument(
            "--sample-percent",
            type=int,
            default=100,
            help="Copy only this percentage of teams, chosen by team id so a rerun picks the same ones.",
        )
        parser.add_argument(
            "--ids-file",
            default=None,
            help="Copy only the logs alerts whose ids this file lists, one per line.",
        )
        parser.add_argument(
            "--disable",
            action="store_true",
            help="Copy nothing. Switch off the existing logs copies instead, keeping their history.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if options["ids_file"] is not None and options["sample_percent"] != 100:
            raise CommandError("--ids-file names the alerts to copy and takes no --sample-percent")
        if options["disable"]:
            if options["sample_percent"] != 100:
                raise CommandError("--disable switches off every copy in scope and takes no --sample-percent")
            disabled = disable_platform_alert_configurations(
                team_id=options["team_id"], alert_ids=_alert_ids(options["ids_file"])
            )
            self.stdout.write(f"Disabled {disabled}")
            return
        try:
            counts = backfill_platform_alert_configurations(
                team_id=options["team_id"],
                sample_percent=options["sample_percent"],
                alert_ids=_alert_ids(options["ids_file"]),
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f"Created {counts.created}, updated {counts.updated}, skipped {counts.skipped}, failed {counts.failed}"
        )


def _alert_ids(path: str | None) -> list[UUID] | None:
    if path is None:
        return None
    try:
        return [UUID(line.strip()) for line in Path(path).read_text().splitlines() if line.strip()]
    except ValueError as error:
        raise CommandError(f"{path} must hold one alert id per line: {error}") from error
