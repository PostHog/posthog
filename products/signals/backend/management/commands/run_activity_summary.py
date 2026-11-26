"""Run one activity summary update for one (team, user) and print what went in and what came out.

The local loop for the filters and the prompt: `--dry-run` calls the model but writes nothing.
"""

import json

from django.core.management.base import BaseCommand, CommandError

from products.signals.backend.activity_summary.config import parse_limits, parse_variant
from products.signals.backend.activity_summary.logic import update_activity_summary
from products.signals.backend.activity_summary.summaries import DEFAULT_MODEL, ServiceTier


class Command(BaseCommand):
    help = "Update the activity summary of one user in one project, and print the input, output and cost."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--user-id", type=int, required=True)
        parser.add_argument("--dry-run", action="store_true", help="Call the model, but write nothing.")
        parser.add_argument("--force", action="store_true", help="Ignore next_eligible_at.")
        parser.add_argument(
            "--limits",
            type=json.loads,
            default=None,
            help="Render limits as JSON, with the clamps of the flag payload, e.g. '{\"max_completion_tokens\": 2000}'.",
        )
        parser.add_argument(
            "--mcp-buffer-days",
            type=int,
            default=None,
            help="Read this many days of the MCP intent buffer into the input. Off by default.",
        )
        parser.add_argument(
            "--model",
            default=DEFAULT_MODEL,
            help="The model of the update, in place of the model split of the flag. Needs prices.",
        )
        parser.add_argument(
            "--service-tier",
            choices=[tier.value for tier in ServiceTier],
            default=ServiceTier.STANDARD.value,
            help="The service tier of the update. Flex needs a flex-capable model with flex prices.",
        )

    def handle(self, *args, **options):
        variant = parse_variant(options["model"], options["service_tier"])
        if variant is None:
            raise CommandError(f"No prices for {options['model']} on the {options['service_tier']} tier.")
        result = update_activity_summary(
            options["team_id"],
            options["user_id"],
            dry_run=options["dry_run"],
            force=options["force"],
            limits=parse_limits(options["limits"]),
            mcp_buffer_days=options["mcp_buffer_days"],
            variant=variant,
        )
        self.stdout.write(f"status: {result.status}, model: {variant.model}, service tier: {variant.service_tier}")
        if result.rendered_input is not None:
            self.stdout.write(f"\nrendered input:\n{result.rendered_input}\n")
        if result.summary is not None:
            self.stdout.write(f"summary:\n{json.dumps(result.summary, indent=2, ensure_ascii=False)}\n")
        if result.error is not None:
            self.stdout.write(f"error: {result.error}")
        self.stdout.write(
            f"tokens in: {result.tokens_in}, tokens out: {result.tokens_out}, "
            f"cost usd: {result.cost_usd}, latency ms: {result.latency_ms}, "
            f"served tier: {result.served_tier}, fell back: {result.fell_back}"
        )
        if result.inputs_used is not None:
            self.stdout.write(f"inputs used: {json.dumps(result.inputs_used, sort_keys=True)}")
        if result.input_watermark is not None:
            self.stdout.write(f"input watermark: {result.input_watermark.isoformat()}")
