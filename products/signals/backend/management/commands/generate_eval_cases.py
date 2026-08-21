"""Generate the large agentic eval datasets (committed JSON under cases/generated/).

Builds 100+ cases per step from the committed synthetic manifest and public OSS repository
registry. The generated JSON is safe to commit and is what the opted-in live suite loads.

Examples::

    python manage.py generate_eval_cases
    python manage.py generate_eval_cases --target 150 --step research
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
    help = "Generate safe, synthetic agentic eval datasets for committed JSON fixtures."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--target", type=int, default=110, help="Target cases per step.")
        parser.add_argument("--step", choices=["research", "repo_selection", "implementation", "all"], default="all")

    def handle(self, *args, **options) -> None:
        _OUT.mkdir(parents=True, exist_ok=True)
        target = options["target"]
        steps = ["research", "repo_selection", "implementation"] if options["step"] == "all" else [options["step"]]
        builders = {
            "research": lambda: build_research_cases(target=target),
            "repo_selection": lambda: build_repo_selection_cases(target=target),
            "implementation": lambda: build_implementation_cases(target=target),
        }
        for step in steps:
            cases = builders[step]()
            path = _OUT / f"{step}.json"
            if not cases:
                self.stdout.write(self.style.WARNING(f"{step}: no cases generated — leaving {path} untouched"))
                continue
            path.write_text(json.dumps(cases, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"{step}: wrote {len(cases)} cases -> {path}"))
            if len(cases) < target and step != "implementation":
                self.stdout.write(
                    f"  note: only {len(cases)} unique synthetic {step} cases are available (target {target})."
                )
