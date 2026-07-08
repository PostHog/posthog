"""CLI wrapper around the example `CustomSignalAgent` subclasses.

Local-only smoke test for the custom-agent layer. Pick which example to run with ``--agent``.

Usage::

    # Cookie poem (no repo, fully static — the minimal example)
    python manage.py run_custom_agent_example --agent cookie_poem --team-id 1

    # Cursed-comment finder (real research against a repo, agentic resolvers)
    python manage.py run_custom_agent_example --agent cursed_comment --team-id 1
    python manage.py run_custom_agent_example --agent cursed_comment --team-id 1 --repository PostHog/posthog

    # Override the prompt, or run in-process without the Temporal harness
    python manage.py run_custom_agent_example --agent cookie_poem --team-id 1 --prompt "Cookies on a rainy day"
    python manage.py run_custom_agent_example --agent cookie_poem --team-id 1 --local
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from asgiref.sync import async_to_sync

from posthog.models import Team

from products.signals.backend.custom_agent import NO_REPO, CustomSignalAgent
from products.signals.backend.custom_agent.examples import cookie_poem_agent, cursed_comment_agent
from products.signals.backend.temporal.custom_agent import run_agent


@dataclass(frozen=True)
class _AgentSpec:
    agent_class: type[CustomSignalAgent]
    default_prompt: str
    # Repository used when neither --repository nor --no-repo is passed.
    # NO_REPO for repo-less agents, None to free-form select from the team's repos.
    default_repository: str | None


AGENTS: dict[str, _AgentSpec] = {
    "cookie_poem": _AgentSpec(
        agent_class=cookie_poem_agent.CookiePoemAgent,
        default_prompt=cookie_poem_agent.DEFAULT_PROMPT,
        default_repository=NO_REPO,
    ),
    "cursed_comment": _AgentSpec(
        agent_class=cursed_comment_agent.CursedCommentAgent,
        default_prompt=cursed_comment_agent.DEFAULT_PROMPT,
        default_repository=None,
    ),
}


class Command(BaseCommand):
    help = "Start one of the example CustomSignalAgents for a team (local-only)."

    def add_arguments(self, parser):
        parser.add_argument("--agent", choices=sorted(AGENTS), required=True, help="Which example agent to run.")
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--prompt", default=None, help="Override the agent's default prompt.")
        parser.add_argument(
            "--repository",
            default=None,
            help="Explicit 'owner/repo' to run against. Omit to use the agent's default (NO_REPO or free-form selection).",
        )
        parser.add_argument(
            "--no-repo",
            action="store_true",
            help="Force the agent to run without a subject repository.",
        )
        parser.add_argument(
            "--local",
            action="store_true",
            help="Run the agent in-process without Temporal (construct + start).",
        )

    def handle(self, *args, **options):
        # Example/smoke-test agents only — never run them against prod teams from a running pod.
        if not settings.DEBUG:
            raise CommandError("run_custom_agent_example is a local-only example; it requires DEBUG=True")

        spec = AGENTS[options["agent"]]
        prompt = options["prompt"] or spec.default_prompt
        repository = self._resolve_repository(spec, options)

        if options["local"]:
            self._run_local(spec.agent_class, team_id=options["team_id"], prompt=prompt, repository=repository)
        else:
            team = Team.objects.select_related("organization").get(id=options["team_id"])
            handle = run_agent(spec.agent_class, team=team, initial_prompt=prompt, repository=repository)
            self.stdout.write(f"Started workflow {handle.workflow_id}")

    @staticmethod
    def _resolve_repository(spec: _AgentSpec, options: dict) -> str | None:
        if options["no_repo"]:
            if options["repository"]:
                raise CommandError("--no-repo and --repository are mutually exclusive")
            return NO_REPO
        if options["repository"]:
            return options["repository"]
        return spec.default_repository

    def _run_local(
        self, agent_class: type[CustomSignalAgent], *, team_id: int, prompt: str, repository: str | None
    ) -> None:
        async def _run() -> None:
            team = await Team.objects.select_related("organization").aget(id=team_id)
            agent = agent_class(team=team, initial_prompt=prompt, repository=repository)
            persisted = await agent.start()
            for report in persisted:
                self.stdout.write(f"persisted report {report.report_id} (task {report.task_id})")

        async_to_sync(_run)()
