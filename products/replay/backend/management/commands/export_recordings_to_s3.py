"""Export a team's session recordings to an S3 bucket the customer owns, one .phrec file per session.

The customer adds an AWS S3 integration with a role ARN to the project, as for an S3 batch export.
Each file plays back in Replay's file playback page.

Usage:
    # Price an export and store the quote. Prints the quote ID.
    python manage.py export_recordings_to_s3 --quote --team-id 1 --region us-east-1 \\
        --date-from 2026-08-01 --date-to 2026-10-31 [--session-ids-file ids.txt]

    # Start the export of a quoted selection.
    python manage.py export_recordings_to_s3 --quote-id <id> --integration-id 7 --bucket my-bucket \\
        --region us-east-1 --prefix replay-export

    # Show the state of a run.
    python manage.py export_recordings_to_s3 --status <workflow id>
"""

import uuid
import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Integration, Team
from posthog.temporal.common.client import async_connect

from products.replay.backend.temporal.export_recordings.quote import Quote, create_quote, load_quote
from products.replay.backend.temporal.export_recordings.types import ExportDestination, ExportRecordingsInput


class Command(BaseCommand):
    help = "Quote or start an export of session recordings to a customer's S3 bucket."

    def add_arguments(self, parser: Any) -> None:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--quote", action="store_true", help="Price the selection and store the quote.")
        mode.add_argument("--quote-id", help="Start the export of this quote's selection.")
        mode.add_argument("--status", metavar="WORKFLOW_ID", help="Show the state of an export run.")
        parser.add_argument("--team-id", type=int)
        parser.add_argument("--date-from", type=date.fromisoformat, help="First UTC day, YYYY-MM-DD.")
        parser.add_argument("--date-to", type=date.fromisoformat, help="Last UTC day, YYYY-MM-DD, inclusive.")
        parser.add_argument("--session-ids-file", type=Path, help="Export only these sessions, one ID per line.")
        parser.add_argument("--region", help="AWS region of the customer's bucket.")
        parser.add_argument(
            "--allow-cross-region", action="store_true", help="Price and allow a bucket outside our replay region."
        )
        parser.add_argument("--integration-id", type=int, help="The project's AWS S3 integration with a role ARN.")
        parser.add_argument("--bucket")
        parser.add_argument("--prefix", default="", help="Key prefix in the customer's bucket.")
        parser.add_argument("--shards-per-day", type=int, default=16)
        parser.add_argument("--max-parallel-shards", type=int, default=32)
        parser.add_argument("--yes", action="store_true", help="Start without asking for confirmation.")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["status"]:
            self.stdout.write(asyncio.run(_describe(options["status"])))
        elif options["quote"]:
            self._quote(options)
        else:
            self._start(options)

    def _quote(self, options: dict[str, Any]) -> None:
        team_id, region = _required(options, "team_id"), _required(options, "region")
        date_from, date_to = _required(options, "date_from"), _required(options, "date_to")
        if date_to < date_from:
            raise CommandError("--date-to is before --date-from")
        Team.objects.get(id=team_id)
        session_ids = None
        if options["session_ids_file"]:
            session_ids = sorted({line.strip() for line in options["session_ids_file"].read_text().splitlines()} - {""})
        quote = create_quote(
            team_id=team_id,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            session_ids=session_ids,
            region=region,
            cross_region=_cross_region(region, options["allow_cross_region"]),
            max_parallel_shards=options["max_parallel_shards"],
        )
        self.stdout.write(format_quote(quote))

    def _start(self, options: dict[str, Any]) -> None:
        quote = load_quote(options["quote_id"])
        if quote is None:
            raise CommandError(f"Quote {options['quote_id']} does not exist")
        if datetime.fromisoformat(quote.valid_until) < datetime.now(UTC):
            raise CommandError(f"Quote {quote.quote_id} expired at {quote.valid_until}. Create a new quote.")
        region = _required(options, "region")
        if region != quote.region:
            raise CommandError(f"The quote priced region {quote.region}, not {region}")
        integration_id, bucket = _required(options, "integration_id"), _required(options, "bucket")
        if not Integration.objects.filter(
            id=integration_id, team_id=quote.team_id, kind=Integration.IntegrationKind.AWS_S3
        ).exists():
            raise CommandError(f"Team {quote.team_id} has no AWS S3 integration {integration_id}")

        run_id = uuid.uuid4().hex
        workflow_input = ExportRecordingsInput(
            team_id=quote.team_id,
            destination=ExportDestination(
                integration_id=integration_id, bucket=bucket, region=region, prefix=options["prefix"]
            ),
            quote_id=quote.quote_id,
            run_id=run_id,
            date_from=quote.date_from,
            date_to=quote.date_to,
            session_ids_key=quote.session_ids_key,
            quoted_at=quote.created_at,
            shards_per_day=options["shards_per_day"],
            max_parallel_shards=options["max_parallel_shards"],
        )
        self.stdout.write(format_quote(quote))
        self.stdout.write(f"Destination: s3://{bucket}/{options['prefix']} ({region}), run {run_id}")
        if not options["yes"] and input("Start the export? [y/N] ").strip().lower() != "y":
            raise CommandError("Not started")
        workflow_id = f"export-recordings-{quote.team_id}-{run_id}"
        asyncio.run(_start_workflow(workflow_input, workflow_id))
        self.stdout.write(self.style.SUCCESS(f"Started {workflow_id}"))


def _required(options: dict[str, Any], name: str) -> Any:
    if options[name] is None:
        raise CommandError(f"--{name.replace('_', '-')} is required")
    return options[name]


def _cross_region(region: str, allowed: bool) -> bool:
    cross_region = region != settings.SESSION_RECORDING_V2_S3_REGION
    if cross_region and not allowed:
        raise CommandError(
            f"Recordings are stored in {settings.SESSION_RECORDING_V2_S3_REGION}. "
            "Pass --allow-cross-region to price the transfer."
        )
    return cross_region


def format_quote(quote: Quote) -> str:
    usage, cost = quote.usage, quote.cost
    return "\n".join(
        [
            f"Quote {quote.quote_id} for team {quote.team_id}, {quote.date_from} to {quote.date_to}"
            + (" (session list)" if quote.session_ids_key else ""),
            f"  Sessions:           {usage.sessions:,}",
            f"  Blocks:             {usage.blocks:,} ({usage.glacier_blocks:,} in Glacier IR)",
            f"  Stored data:        {usage.bytes / 1e9:,.1f} GB ({usage.glacier_bytes / 1e9:,.1f} GB in Glacier IR)",
            f"  Standard GETs:      ${cost.standard_gets_usd:,.2f}",
            f"  Glacier IR GETs:    ${cost.glacier_ir_gets_usd:,.2f}",
            f"  Glacier retrieval:  ${cost.glacier_ir_retrieval_usd:,.2f}",
            f"  Transfer:           ${cost.transfer_usd:,.2f}" + (" (cross-region)" if quote.cross_region else ""),
            f"  Compute:            ${cost.compute_usd:,.2f}",
            f"  Our cost:           ${cost.total_usd:,.2f}",
            f"  Estimated duration: {cost.estimated_hours} hours at {quote.max_parallel_shards} parallel shards",
            f"  Best effort:        {usage.best_effort_sessions:,} sessions expire soon and may expire before export",
            f"  Valid until:        {quote.valid_until}",
        ]
    )


async def _start_workflow(workflow_input: ExportRecordingsInput, workflow_id: str) -> None:
    client = await async_connect()
    await client.start_workflow(
        "export-recordings", workflow_input, id=workflow_id, task_queue=settings.SESSION_REPLAY_TASK_QUEUE
    )


async def _describe(workflow_id: str) -> str:
    client = await async_connect()
    description = await client.get_workflow_handle(workflow_id).describe()
    status = description.status.name if description.status else "UNKNOWN"
    return f"{workflow_id}: {status}, started {description.start_time}, closed {description.close_time}"
