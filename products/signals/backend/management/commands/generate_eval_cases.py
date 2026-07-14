"""Generate the large agentic eval datasets (committed JSON under cases/generated/).

Builds 100+ cases per step, grounded in the team's real data (repo cache, error-tracking
issues, events, experiments) plus templated variety. Requires the local stack (DB/ClickHouse).
Run once (or after the project data changes); the generated JSON is what the live suite loads.

Examples::

    python manage.py generate_eval_cases                 # all steps, ~110 each, team 1
    python manage.py generate_eval_cases --team-id 2 --target 150 --step research
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.core.management.base import BaseCommand

from products.signals.eval.agentic.generators.build import (
    build_implementation_cases,
    build_repo_selection_cases,
    build_research_cases,
)

logger = logging.getLogger(__name__)

# .../signals/backend/management/commands/<file> -> parents[3] == .../signals
_OUT = Path(__file__).resolve().parents[3] / "eval" / "agentic" / "cases" / "generated"


class Command(BaseCommand):
    help = "Generate large agentic eval datasets (committed JSON) grounded in the project's data."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, default=1)
        parser.add_argument("--target", type=int, default=110, help="Target cases per step.")
        parser.add_argument("--step", choices=["research", "repo_selection", "implementation", "all"], default="all")

    def handle(self, *args, **options) -> None:
        _OUT.mkdir(parents=True, exist_ok=True)
        team_id = options["team_id"]
        target = options["target"]
        steps = ["research", "repo_selection", "implementation"] if options["step"] == "all" else [options["step"]]
        builders = {
            "research": lambda: build_research_cases(team_id, target=target),
            "repo_selection": lambda: build_repo_selection_cases(team_id, target=target),
            "implementation": lambda: build_implementation_cases(target=target),
        }
        for step in steps:
            cases = builders[step]()
            path = _OUT / f"{step}.json"
            if not cases:
                self.stdout.write(
                    self.style.WARNING(
                        f"{step}: no cases generated (missing source data, e.g. no GitHub "
                        f"integration) — leaving {path} untouched"
                    )
                )
                continue
            path.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"{step}: wrote {len(cases)} cases -> {path}"))
            if len(cases) < target and step != "implementation":
                self.stdout.write(
                    f"  note: only {len(cases)} {step} cases available from project data "
                    f"(target {target}); add more source data or raise --target elsewhere."
                )
