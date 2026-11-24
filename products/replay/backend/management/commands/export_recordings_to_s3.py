"""Export a team's session recordings to an S3 bucket the customer owns, one .phrec file per session.

The customer creates a role that trusts PostHog's recording-exports role and sends us its ARN.
Each file plays back in Replay's file playback page.

Usage:
    # Price an export and store the quote. Prints the quote ID.
    python manage.py export_recordings_to_s3 --quote --team-id 1 --region us-east-1 \\
        --date-from 2026-08-01 --date-to 2026-10-31 [--session-ids-file ids.txt | --playlist <short id>]

    # Start the export of a quoted selection.
    python manage.py export_recordings_to_s3 --quote-id <id> --role-arn <arn> --bucket my-bucket \\
        --region us-east-1 --prefix replay-export

    # Show the state of a run.
    python manage.py export_recordings_to_s3 --status <workflow id>
"""

import sys
import uuid
import asyncio
import argparse
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from posthog.clickhouse.client.connection import set_default_clickhouse_workload_type
from posthog.clickhouse.workload import Workload
from posthog.models import OrganizationMembership, Team
from posthog.models.activity_logging.activity_log import Detail, Trigger, log_activity
from posthog.models.integration.aws import is_unique_aws_role_by_organization_id
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.errors import describe_failure

from products.replay.backend.temporal.export_recordings.activities import destination_error
from products.replay.backend.temporal.export_recordings.quote import (
    Quote,
    SelectionError,
    create_quote,
    load_quote,
    playlist_session_ids,
)
from products.replay.backend.temporal.export_recordings.types import ExportDestination, ExportRecordingsInput
from products.replay.backend.temporal.export_recordings.workflow import shard_name


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
        selection = parser.add_mutually_exclusive_group()
        selection.add_argument("--session-ids-file", type=Path, help="Export only these sessions, one ID per line.")
        selection.add_argument(
            "--playlist",
            metavar="SHORT_ID",
            help="Export only the sessions a saved recordings filter matches in the date range.",
        )
        parser.add_argument("--region", help="AWS region of the customer's bucket.")
        parser.add_argument(
            "--allow-cross-region", action="store_true", help="Price and allow a bucket outside our replay region."
        )
        parser.add_argument("--role-arn", help="The customer's IAM role, trusting PostHog's recording-exports role.")
        parser.add_argument(
            "--approved-by", metavar="EMAIL", help="The admin of the team's organization who sent the role ARN."
        )
        parser.add_argument("--bucket")
        parser.add_argument("--prefix", default="", help="Key prefix in the customer's bucket.")
        parser.add_argument(
            "--kms-key-id", help="Encrypt with this KMS key: a key ID in the role's account, or a key ARN."
        )
        parser.add_argument(
            "--shards-per-day", type=_positive_int, default=16, help="Quote only. Raise it when a shard is too big."
        )
        parser.add_argument("--max-parallel-shards", type=_positive_int, default=32)
        parser.add_argument(
            "--shards",
            type=_shard_list,
            help="Run only these shards, as YYYY-MM-DD:N,..., for example the failed shards an earlier run lists.",
        )
        parser.add_argument("--yes", action="store_true", help="Start without asking for confirmation.")

    def handle(self, *args: Any, **options: Any) -> None:
        # Every query this one-off process runs is an export scan, so none should compete with interactive queries.
        set_default_clickhouse_workload_type(Workload.OFFLINE)
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
        if date_to >= datetime.now(UTC).date():
            raise CommandError(
                "--date-to must be before today (UTC), so every session in the range has finished recording"
            )
        team = Team.objects.get(id=team_id)
        cross_region = _cross_region(region, options["allow_cross_region"])
        try:
            session_ids, selection = None, "every session in the range"
            if options["session_ids_file"]:
                lines = options["session_ids_file"].read_text().splitlines()
                session_ids, selection = sorted({line.strip() for line in lines} - {""}), "a list of session IDs"
            elif options["playlist"]:
                session_ids = playlist_session_ids(
                    team, options["playlist"], date_from.isoformat(), date_to.isoformat()
                )
                selection = f"saved recordings filter {options['playlist']}"
            quote = create_quote(
                team_id=team_id,
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                session_ids=session_ids,
                region=region,
                cross_region=cross_region,
                shards_per_day=options["shards_per_day"],
                max_parallel_shards=options["max_parallel_shards"],
                selection=selection,
            )
        except SelectionError as e:
            raise CommandError(str(e)) from e
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
        # One workflow ID per quote. Temporal refuses a second start unless the earlier run failed.
        workflow_id = f"export-recordings-{quote.team_id}-{quote.quote_id}"
        if options["shards"]:
            check_shard_rerun(asyncio.run(_last_run_status(workflow_id)))
        role_arn, bucket = _required(options, "role_arn"), _required(options, "bucket")
        approved_by = _required(options, "approved_by")
        prefix, kms_key_id = options["prefix"], options["kms_key_id"]
        only_shards = options["shards"]
        if only_shards:
            quoted_days = (date.fromisoformat(quote.date_from), date.fromisoformat(quote.date_to))
            for name in only_shards:
                day, shard = name.split(":")
                if not quoted_days[0] <= date.fromisoformat(day) <= quoted_days[1]:
                    raise CommandError(f"Shard {name} is outside the quoted range {quote.date_from} to {quote.date_to}")
                if int(shard) >= quote.shards_per_day:
                    raise CommandError(f"Shard {name} is not below the quote's {quote.shards_per_day} shards per day")
        run_id = uuid.uuid4().hex
        destination = ExportDestination(
            role_arn=role_arn, bucket=bucket, region=region, prefix=prefix, kms_key_id=kms_key_id
        )
        if error := destination_error(destination):
            raise CommandError(error)
        organization_id = Team.objects.values_list("organization_id", flat=True).get(id=quote.team_id)
        # Same rule as AWS integrations: a role another organization registered must not receive this team's data.
        if not is_unique_aws_role_by_organization_id(role_arn, str(organization_id)):
            raise CommandError(f"{role_arn} is registered by another organization")
        check_approver(organization_id, approved_by)
        workflow_input = ExportRecordingsInput(
            team_id=quote.team_id,
            destination=destination,
            quote_id=quote.quote_id,
            run_id=run_id,
            date_from=quote.date_from,
            date_to=quote.date_to,
            session_ids_prefix=quote.session_ids_prefix,
            shards_per_day=quote.shards_per_day,
            max_parallel_shards=options["max_parallel_shards"],
            only_shards=only_shards,
        )
        self.stdout.write(format_quote(quote))
        encryption = f", KMS key {kms_key_id}" if kms_key_id else ""
        shards = f", only shards {','.join(only_shards)}" if only_shards else ""
        self.stdout.write(
            f"Destination: s3://{bucket}/{prefix} ({region}{encryption}) as {role_arn}, approved by {approved_by}, "
            f"run {run_id}{shards}"
        )
        if not options["yes"]:
            # A non-interactive exec has no terminal to answer the prompt.
            if not sys.stdin.isatty():
                raise CommandError("Not started. Check the quote and destination above, then rerun with --yes.")
            if input("Start the export? [y/N] ").strip().lower() != "y":
                raise CommandError("Not started")
        # Written first and fail-closed, so an export never runs without its entry in the organization's activity log.
        record_export(organization_id, workflow_input, workflow_id, approved_by)
        try:
            asyncio.run(_start_workflow(workflow_input, workflow_id))
        except WorkflowAlreadyStartedError as e:
            raise CommandError(
                f"{workflow_id} is running or finished. A quote starts again only after a failed run."
            ) from e
        self.stdout.write(self.style.SUCCESS(f"Started {workflow_id}"))


def check_approver(organization_id: UUID, email: str) -> None:
    is_admin = OrganizationMembership.objects.filter(
        organization_id=organization_id,
        user__email__iexact=email,
        user__is_active=True,
        level__gte=OrganizationMembership.Level.ADMIN,
    ).exists()
    if not is_admin:
        raise CommandError(f"{email} is not an admin of the team's organization")


def record_export(
    organization_id: UUID, workflow_input: ExportRecordingsInput, workflow_id: str, approved_by: str
) -> None:
    """Lets the customer's organization see in its activity log which AWS account received the team's recordings."""
    destination = workflow_input.destination
    log_activity(
        organization_id=organization_id,
        team_id=workflow_input.team_id,
        user=None,
        was_impersonated=False,
        item_id=workflow_input.quote_id,
        scope="Replay",
        activity="exported",
        strict=True,
        detail=Detail(
            name=f"Recordings exported to s3://{destination.bucket}/{destination.prefix}",
            trigger=Trigger(
                job_type="export_recordings_to_s3",
                job_id=workflow_id,
                payload={
                    "role_arn": destination.role_arn,
                    "bucket": destination.bucket,
                    "prefix": destination.prefix,
                    "region": destination.region,
                    "kms_key_id": destination.kms_key_id,
                    "run_id": workflow_input.run_id,
                    "approved_by": approved_by,
                },
            ),
        ),
    )


def check_shard_rerun(last_run_status: WorkflowExecutionStatus | None) -> None:
    # A subset that succeeds completes the quote's workflow ID, which strands the shards it left out.
    if last_run_status != WorkflowExecutionStatus.FAILED:
        raise CommandError("--shards reruns the failed shards of an earlier run. Start the whole quote first.")


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"{value} is not a positive integer")
    return number


def _shard_list(value: str) -> tuple[str, ...]:
    """Parse YYYY-MM-DD:N names into the exact spelling the workflow compares against."""
    shards: list[str] = []
    for name in (name.strip() for name in value.split(",") if name.strip()):
        day, _, shard = name.partition(":")
        try:
            number = int(shard)
            if number < 0:
                raise ValueError(shard)
            shards.append(shard_name(date.fromisoformat(day).isoformat(), number))
        except ValueError as e:
            raise argparse.ArgumentTypeError(f"{name} is not YYYY-MM-DD:N") from e
    if not shards:
        raise argparse.ArgumentTypeError("--shards names no shard")
    return tuple(shards)


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
            + f", {quote.selection}",
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
        "export-recordings",
        workflow_input,
        id=workflow_id,
        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )


async def _last_run_status(workflow_id: str) -> WorkflowExecutionStatus | None:
    client = await async_connect()
    try:
        return (await client.get_workflow_handle(workflow_id).describe()).status
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return None
        raise


async def _describe(workflow_id: str) -> str:
    client = await async_connect()
    handle = client.get_workflow_handle(workflow_id)
    description = await handle.describe()
    status = description.status.name if description.status else "UNKNOWN"
    line = f"{workflow_id}: {status}, started {description.start_time}, closed {description.close_time}"
    if description.status != WorkflowExecutionStatus.FAILED:
        return line
    try:
        await handle.result()
    except WorkflowFailureError as e:
        return f"{line}\n{failure_message(e)}"
    return line


def failure_message(error: WorkflowFailureError) -> str:
    # The client error is not a Temporal FailureError, so unwrapping starts at its cause.
    return describe_failure(error.cause)
