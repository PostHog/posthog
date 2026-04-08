"""Local dev tool for manually emitting a signal from a Conversations ticket. DEBUG only.

Bypasses the hourly Temporal schedule and 1-hour cooldown so you can iterate
on the conversations signal pipeline immediately.

Usage:
    python manage.py emit_conversation_signal --team-id 1 --ticket 1
    python manage.py emit_conversation_signal --team-id 1 --ticket 1 --skip-llm
    python manage.py emit_conversation_signal --team-id 1 --ticket 1 --dry-run
"""

import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Team
from posthog.models.comment import Comment
from posthog.temporal.data_imports.signals.conversations_tickets import CONVERSATIONS_TICKETS_CONFIG
from posthog.temporal.data_imports.signals.pipeline import (
    build_emitter_outputs,
    filter_actionable,
    summarize_long_descriptions,
)

from products.conversations.backend.models import Ticket
from products.signals.backend.api import emit_signal


class Command(BaseCommand):
    help = "Local dev tool: emit a signal from a specific Conversations ticket. DEBUG only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            required=True,
            help="Team ID that owns the ticket",
        )
        parser.add_argument(
            "--ticket",
            type=int,
            required=True,
            help="Ticket number (as shown in the URL, e.g. 1 for /tickets/1)",
        )
        parser.add_argument(
            "--skip-llm",
            action="store_true",
            help="Skip LLM summarization and actionability checks (faster iteration)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build the signal output but don't actually emit it",
        )
        parser.add_argument(
            "--no-mark",
            action="store_true",
            help="Don't set signal_emitted_at on the ticket (allows re-running)",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True")

        team_id = options["team_id"]
        ticket_number = options["ticket"]
        skip_llm = options["skip_llm"]
        dry_run = options["dry_run"]
        no_mark = options["no_mark"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            raise CommandError(f"Team {team_id} not found")

        try:
            ticket = Ticket.objects.get(ticket_number=ticket_number, team=team)
        except Ticket.DoesNotExist:
            raise CommandError(f"Ticket #{ticket_number} not found for team {team_id}")
        self.stdout.write(f"Ticket: #{ticket.ticket_number} ({ticket.id})")
        self.stdout.write(f"  Channel: {ticket.channel_source}")
        self.stdout.write(f"  Status: {ticket.status}")
        self.stdout.write(f"  Created: {ticket.created_at}")
        self.stdout.write(f"  Signal emitted: {ticket.signal_emitted_at or 'never'}")
        self.stdout.write("")

        record = self._build_record(team, ticket)
        message_count = len(record.get("messages", []))
        self.stdout.write(f"Fetched {message_count} messages for ticket")

        if message_count == 0:
            self.stdout.write(self.style.WARNING("No messages found — emitter will return None"))

        # Run through emitter
        config = CONVERSATIONS_TICKETS_CONFIG
        outputs, error_count = build_emitter_outputs(
            team_id=team.id,
            records=[record],
            emitter=config.emitter,
        )
        if not outputs:
            if error_count > 0:
                self.stdout.write(self.style.ERROR("Emitter failed for this ticket"))
            else:
                self.stdout.write(self.style.WARNING("Emitter returned None (ticket skipped)"))
            return

        output = outputs[0]
        self.stdout.write(self.style.SUCCESS("Emitter output:"))
        self.stdout.write(f"  source_product: {output.source_product}")
        self.stdout.write(f"  source_type: {output.source_type}")
        self.stdout.write(f"  source_id: {output.source_id}")
        self.stdout.write(f"  weight: {output.weight}")
        self.stdout.write(f"  description ({len(output.description)} chars):")
        # Truncate for display
        preview = output.description[:500] + ("..." if len(output.description) > 500 else "")
        self.stdout.write(f"    {preview}")
        self.stdout.write(f"  extra: {output.extra}")
        self.stdout.write("")

        if not skip_llm:
            self.stdout.write("Running LLM pipeline (summarization + actionability)...")
            outputs = asyncio.run(self._run_llm_pipeline(config, outputs))
            if not outputs:
                self.stdout.write(self.style.WARNING("Filtered as NOT_ACTIONABLE by LLM"))
                return
            output = outputs[0]
            self.stdout.write(self.style.SUCCESS(f"After LLM pipeline ({len(output.description)} chars):"))
            preview = output.description[:500] + ("..." if len(output.description) > 500 else "")
            self.stdout.write(f"    {preview}")
            self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — not emitting signal"))
            return

        self.stdout.write("Emitting signal...")
        asyncio.run(
            emit_signal(
                team=team,
                source_product=output.source_product,
                source_type=output.source_type,
                source_id=output.source_id,
                description=output.description,
                weight=output.weight,
                extra=output.extra,
            )
        )
        self.stdout.write(self.style.SUCCESS("Signal emitted"))

        if not no_mark:
            from django.utils import timezone

            Ticket.objects.filter(id=ticket.id).update(signal_emitted_at=timezone.now())
            self.stdout.write(f"Marked ticket signal_emitted_at = now()")
        else:
            self.stdout.write("Skipped marking signal_emitted_at (--no-mark)")

    def _build_record(self, team: Team, ticket: Ticket) -> dict[str, Any]:
        config = CONVERSATIONS_TICKETS_CONFIG
        # Build record dict matching the shape the emitter expects
        record: dict[str, Any] = {}
        for field in config.fields:
            record[field] = getattr(ticket, field, None)

        # Fetch messages as (author_type, content) tuples matching the fetcher's format
        comments = (
            Comment.objects.filter(
                team=team,
                scope="conversations_ticket",
                item_id=str(ticket.id),
                deleted=False,
            )
            .order_by("created_at")
            .values_list("content", "item_context")
        )
        record["messages"] = [
            ((ctx or {}).get("author_type", "customer"), content) for content, ctx in comments if content
        ]
        return record

    async def _run_llm_pipeline(self, config, outputs):
        from unittest.mock import patch

        extra = {"team_id": "dev", "source_type": "conversations", "schema_name": "tickets"}

        # activity.heartbeat() fails outside Temporal — stub it for local dev
        with patch("posthog.temporal.data_imports.signals.pipeline.activity"):
            if config.summarization_prompt and config.description_summarization_threshold_chars:
                outputs = await summarize_long_descriptions(
                    outputs=outputs,
                    summarization_prompt=config.summarization_prompt,
                    threshold=config.description_summarization_threshold_chars,
                    extra=extra,
                )
            if config.actionability_prompt:
                outputs = await filter_actionable(
                    outputs=outputs,
                    actionability_prompt=config.actionability_prompt,
                    extra=extra,
                )
        return outputs
