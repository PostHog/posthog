"""Run the agentic eval suite (research / repo selection / implementation).

The local entrypoint for the agentic eval framework. Defaults to deterministic ``replay``
mode (no stack, no LLM), so ``python manage.py run_agentic_eval`` works anywhere. ``live``
and ``record`` modes drive the real agent and need the local stack + Docker sandbox; see
``products/signals/eval/agentic/README.md``.

Examples::

    python manage.py run_agentic_eval                       # all steps, replay
    python manage.py run_agentic_eval --step research       # one step
    python manage.py run_agentic_eval --judge               # add LLM-judge scorers
    python manage.py run_agentic_eval --capture             # emit $ai_evaluation events
    python manage.py run_agentic_eval --min-pass-rate 1.0   # gate CI (nonzero exit on miss)
    python manage.py run_agentic_eval --step research --mode live --team-id 42 --judge
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError

from products.signals.eval.agentic.run import run_and_report
from products.signals.eval.agentic.suites import STEPS

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the agentic eval suite for the signals pipeline."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--step", choices=[*STEPS, "all"], default="all", help="Which step to evaluate.")
        parser.add_argument(
            "--mode",
            choices=["replay", "record", "live"],
            default="replay",
            help="replay = deterministic (default); record/live drive the real agent (needs the stack).",
        )
        parser.add_argument("--judge", action="store_true", help="Enable LLM-as-judge scorers (uses the gateway).")
        parser.add_argument("--capture", action="store_true", help="Emit $ai_evaluation events to PostHog.")
        parser.add_argument("--team-id", type=int, default=1, help="Team id for live mode + cost attribution.")
        parser.add_argument("--user-id", type=int, default=1, help="User id for live mode sandbox context.")
        parser.add_argument("--case", default=None, help="Only run cases whose id contains this substring.")
        parser.add_argument(
            "--sample",
            type=int,
            default=None,
            help="Run a deterministic random sample of N cases (for the large suite).",
        )
        parser.add_argument("--seed", type=int, default=1337, help="Seed for --sample (reproducible subsets).")
        parser.add_argument("--concurrency", type=int, default=4, help="Max concurrent live cases (live mode only).")
        parser.add_argument(
            "--min-pass-rate",
            type=float,
            default=None,
            help="Exit nonzero if any step's pass rate is below this (for CI gating).",
        )

    def handle(self, *args, **options) -> None:
        steps = list(STEPS) if options["step"] == "all" else [options["step"]]
        if options["mode"] != "replay":
            self.stderr.write(
                f"mode={options['mode']} drives the real agent — requires the local stack + Docker sandbox "
                "(SANDBOX_PROVIDER=docker, DEBUG=1). See products/signals/eval/agentic/README.md."
            )

        results = run_and_report(
            steps,
            mode=options["mode"],
            judge_enabled=options["judge"],
            capture=options["capture"],
            team_id=options["team_id"],
            user_id=options["user_id"],
            case_filter=options["case"],
            sample=options["sample"],
            seed=options["seed"],
            concurrency=options["concurrency"],
        )

        min_pass = options["min_pass_rate"]
        if min_pass is not None:
            failing = {step: s.pass_rate for step, s in results.items() if s.pass_rate < min_pass}
            if failing:
                raise CommandError(
                    "pass-rate gate not met: "
                    + ", ".join(f"{step}={rate:.0%}" for step, rate in failing.items())
                    + f" (required >= {min_pass:.0%})"
                )
        self.stdout.write(self.style.SUCCESS("agentic eval complete"))
