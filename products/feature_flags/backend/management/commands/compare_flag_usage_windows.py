import json
from argparse import ArgumentParser
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from posthog.constants import FlagRequestType

from products.feature_flags.backend.usage_comparison import compare_flag_usage_windows


class Command(BaseCommand):
    help = "Compare flag usage exports with realtime counts over their source bucket windows (read only)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--export-date", required=True, help="UTC date, YYYY-MM-DD")
        parser.add_argument("--request-type", choices=["decide", "local_evaluation"], default="decide")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            export_day = datetime.strptime(options["export_date"], "%Y-%m-%d").replace(tzinfo=UTC)
            comparisons = compare_flag_usage_windows(
                team_id=options["team_id"],
                export_day=export_day,
                request_type=FlagRequestType(options["request_type"]),
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            json.dumps(
                {
                    "team_id": options["team_id"],
                    "export_date": options["export_date"],
                    "note": "Source windows can overlap or contain gaps. Do not sum these realtime counts. Producer flushes can cross bucket boundaries.",
                    "batches": [
                        {
                            "exported_at": row.exported_at.isoformat(),
                            "source_start_inclusive": row.source_start.isoformat(),
                            "source_end_exclusive": row.source_end.isoformat(),
                            "legacy": row.legacy,
                            "realtime": row.realtime,
                            "delta": row.realtime - row.legacy,
                        }
                        for row in comparisons
                    ],
                }
            )
        )
