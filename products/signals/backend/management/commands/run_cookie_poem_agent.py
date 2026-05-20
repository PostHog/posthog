"""Thin CLI wrapper around `CookiePoemAgent`.

Usage::

    # Through Temporal (default)
    python manage.py run_cookie_poem_agent --team-id 1
    python manage.py run_cookie_poem_agent --team-id 1 --prompt "Cookies on a rainy day"

    # Direct, no Temporal harness (just construct + `await agent.start()`).
    # Useful for testing the agent locally without spinning up the workflow.
    python manage.py run_cookie_poem_agent --team-id 1 --local
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from asgiref.sync import async_to_sync

from posthog.models import Team

from products.signals.backend.custom_agent import NO_REPO
from products.signals.backend.custom_agent.examples.cookie_poem_agent import DEFAULT_PROMPT, CookiePoemAgent
from products.signals.backend.temporal.custom_agent import run_agent


class Command(BaseCommand):
    help = "Start the example CookiePoemAgent for a team."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--prompt", default=DEFAULT_PROMPT)
        parser.add_argument(
            "--local",
            action="store_true",
            help="Run the agent in-process without Temporal (construct + start).",
        )

    def handle(self, *args, **options):
        if options["local"]:
            self._run_local(team_id=options["team_id"], prompt=options["prompt"])
        else:
            team = Team.objects.select_related("organization").get(id=options["team_id"])
            handle = run_agent(CookiePoemAgent, team=team, initial_prompt=options["prompt"], repository=NO_REPO)
            self.stdout.write(f"Started workflow {handle.workflow_id}")

    def _run_local(self, *, team_id: int, prompt: str) -> None:
        async def _run() -> None:
            team = await Team.objects.select_related("organization").aget(id=team_id)
            agent = CookiePoemAgent(team=team, initial_prompt=prompt, repository=NO_REPO)
            persisted = await agent.start()
            for report in persisted:
                self.stdout.write(f"persisted report {report.report_id} (task {report.task_id})")

        async_to_sync(_run)()
