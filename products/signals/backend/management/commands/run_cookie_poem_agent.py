"""Thin CLI wrapper around `run_cookie_poem_agent`.

Usage::

    python manage.py run_cookie_poem_agent --team-id 1
    python manage.py run_cookie_poem_agent --team-id 1 --prompt "Cookies on a rainy day"
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from products.signals.backend.custom_agent.examples.cookie_poem_agent import DEFAULT_PROMPT, run_cookie_poem_agent


class Command(BaseCommand):
    help = "Start the example CookiePoemAgent for a team."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--prompt", default=DEFAULT_PROMPT)

    def handle(self, *args, **options):
        handle = run_cookie_poem_agent(team_id=options["team_id"], prompt=options["prompt"])
        self.stdout.write(f"Started workflow {handle.workflow_id}")
