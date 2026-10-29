"""Run one activity summary update for one (team, user) and print what went in and what came out.

The local loop for the filters and the prompt: `--dry-run` calls the model but writes nothing.
"""

import json

from django.core.management.base import BaseCommand

from products.signals.backend.activity_summary.config import parse_limits
from products.signals.backend.activity_summary.logic import update_activity_summary


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

    def handle(self, *args, **options):
        result = update_activity_summary(
            options["team_id"],
            options["user_id"],
            dry_run=options["dry_run"],
            force=options["force"],
            limits=parse_limits(options["limits"]),
        )
        self.stdout.write(f"status: {result.status}")
        if result.rendered_input is not None:
            self.stdout.write(f"\nrendered input:\n{result.rendered_input}\n")
        if result.summary is not None:
            self.stdout.write(f"summary:\n{json.dumps(result.summary, indent=2, ensure_ascii=False)}\n")
        if result.error is not None:
            self.stdout.write(f"error: {result.error}")
        self.stdout.write(
            f"tokens in: {result.tokens_in}, tokens out: {result.tokens_out}, "
            f"cost usd: {result.cost_usd}, latency ms: {result.latency_ms}"
        )
        if result.inputs_used is not None:
            self.stdout.write(f"inputs used: {json.dumps(result.inputs_used, sort_keys=True)}")
        if result.input_watermark is not None:
            self.stdout.write(f"input watermark: {result.input_watermark.isoformat()}")
