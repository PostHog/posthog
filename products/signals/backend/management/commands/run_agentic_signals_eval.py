"""Run the agentic eval suite (research / repo selection / implementation / scout).

The local entrypoint for the agentic eval framework. Defaults to deterministic ``replay``
mode (no stack, no LLM), so ``python manage.py run_agentic_signals_eval`` works anywhere. ``live``
and ``record`` modes drive the real agent and need the local stack + Docker sandbox; see
``products/signals/eval/agentic/README.md``.

Examples::

    python manage.py run_agentic_signals_eval                       # all steps, replay
    python manage.py run_agentic_signals_eval --step research       # one step
    python manage.py run_agentic_signals_eval --judge               # add LLM-judge scorers
    python manage.py run_agentic_signals_eval --capture             # emit $ai_evaluation events
    python manage.py run_agentic_signals_eval --min-pass-rate 1.0   # gate CI (nonzero exit on miss)
    python manage.py run_agentic_signals_eval --step research --mode live --team-id 42 --judge
    python manage.py run_agentic_signals_eval --step scout --mode live --sample 20
    python manage.py run_agentic_signals_eval --step scout --mode live --runtime-adapter claude --model claude-opus-4-8
    python manage.py run_agentic_signals_eval --step scout --mode live --judge --judge-model claude-fable-5
"""

from __future__ import annotations

import os
import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.signals.eval.agentic.run import run_and_report
from products.signals.eval.agentic.suites import STEPS

logger = logging.getLogger(__name__)


def _docker_reachable() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _sandbox_provider() -> str | None:
    # Provisioning happens in the temporal worker, whose env comes from the stack's
    # env files — this CLI process often lacks the var, so fall back to those files.
    provider = getattr(settings, "SANDBOX_PROVIDER", None)
    if provider:
        return provider
    for name in (".env.local", ".env"):
        path = Path(settings.BASE_DIR) / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.startswith("SANDBOX_PROVIDER="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def _preflight_agent_mode(mode: str) -> None:
    missing: list[str] = []
    if not settings.DEBUG:
        missing.append("DEBUG=1 (sandbox runs are local-dev only)")
    if _sandbox_provider() != "docker":
        missing.append("SANDBOX_PROVIDER=docker")
    if not _docker_reachable():
        missing.append("a reachable Docker daemon (`docker info` failed — is Docker running?)")
    if missing:
        raise CommandError(
            f"mode={mode} drives the real agent but the environment is not ready. Missing:\n  - "
            + "\n  - ".join(missing)
            + "\nSee products/signals/eval/agentic/README.md."
        )


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
        parser.add_argument("--judge-model", default=None, help="Model to use for LLM-as-judge scorers.")
        parser.add_argument("--capture", action="store_true", help="Emit $ai_evaluation events to PostHog.")
        parser.add_argument("--team-id", type=int, default=1, help="Team id for live mode + cost attribution.")
        parser.add_argument("--user-id", type=int, default=1, help="User id for live mode sandbox context.")
        parser.add_argument(
            "--runtime-adapter",
            choices=["claude", "codex"],
            default=None,
            help="Override the runtime adapter for live/record runs.",
        )
        parser.add_argument("--model", default=None, help="Override the model for live/record runs.")
        parser.add_argument(
            "--reasoning-effort",
            choices=["low", "medium", "high", "xhigh", "max"],
            default=None,
            help="Override reasoning effort for live/record runs.",
        )
        parser.add_argument("--case", default=None, help="Only run cases whose id contains this substring.")
        parser.add_argument(
            "--sample",
            type=int,
            default=None,
            help="Run a deterministic random sample of N cases (for the large suite).",
        )
        parser.add_argument("--seed", type=int, default=1337, help="Seed for --sample (reproducible subsets).")
        parser.add_argument("--concurrency", type=int, default=8, help="Max concurrent live cases (live mode only).")
        parser.add_argument(
            "--include-generated",
            action="store_true",
            help="Include the generated bulk cases in live/record mode (replay always includes them).",
        )
        parser.add_argument(
            "--min-pass-rate",
            type=float,
            default=None,
            help="Exit nonzero if any step's pass rate is below this (for CI gating).",
        )

    def handle(self, *args, **options) -> None:
        steps = list(STEPS) if options["step"] == "all" else [options["step"]]
        if options["mode"] != "replay":
            _preflight_agent_mode(options["mode"])
        if options["capture"] and not os.environ.get("POSTHOG_PROJECT_API_KEY"):
            raise CommandError("--capture requires POSTHOG_PROJECT_API_KEY — events would be silently dropped")

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
            include_generated=options["include_generated"] or None,
            runtime_adapter=options["runtime_adapter"],
            model=options["model"],
            reasoning_effort=options["reasoning_effort"],
            judge_model=options["judge_model"],
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
