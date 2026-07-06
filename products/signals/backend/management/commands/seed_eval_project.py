"""Seed the synthetic eval project (hedgebox dataset) for live agentic evals.

Requires the local stack (Postgres + ClickHouse + Kafka). Replay-mode evals do NOT need this.

Examples::

    python manage.py seed_eval_project                 # fresh demo org/user/project
    python manage.py seed_eval_project --team-id 42    # seed an existing project in place
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from products.signals.eval.agentic.project.manifest import DEFAULT_MANIFEST
from products.signals.eval.agentic.project.seed import seed_eval_project

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed the synthetic eval project with representative, queryable data (hedgebox)."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--team-id", type=int, default=None, help="Seed this existing project (else create one).")

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_eval_project is a local-dev tool; run with DEBUG=1.")
        self.stdout.write(
            f"Seeding eval project (product={DEFAULT_MANIFEST.product}, seed={DEFAULT_MANIFEST.seed}, "
            f"n_clusters={DEFAULT_MANIFEST.n_clusters})…"
        )
        seed_eval_project(team_id=options["team_id"])
        self.stdout.write(self.style.SUCCESS("eval project seeded"))
        self.stdout.write(
            "Next: connect a GitHub integration (repo-selection/implementation candidates) and run\n"
            "  python manage.py run_agentic_eval --mode live --team-id <id> --judge"
        )
