"""Smoke test: run the autoresearch campaign in a real PostHog sandbox.

Creates a Task pointed at ``PostHog/posthog``, mints a short-lived OAuth token
scoped to ``clickhouse_perf:test_read``, and hands the sandbox agent a tight
instruction to invoke ``products/query_performance_ai/scripts/smoke_test.py``.

This is the dev-loop "does the whole thing work end-to-end?" check. It uses
the existing ``sandbox_ask`` / ``custom_prompt_runner`` plumbing rather than a
bespoke Temporal workflow — simpler to iterate on until we build the
production ``autoresearch_campaign`` mode.

Caveat: the OAuth token is interpolated into the prompt text (so the agent
can pass it to smoke_test.py as a CLI arg). Prompts are logged to Redis
streams, so treat this as a **dev-only** path. The production autoresearch
Task mode will inject the token via the sandbox env instead.
"""

from __future__ import annotations

import asyncio
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.tasks.backend.services.custom_prompt_runner import CustomPromptSandboxContext, run_prompt
from products.tasks.backend.temporal.process_task.activities.run_autoresearch_campaign import (
    LLM_GATEWAY_PRODUCT_SLUG,
)


_DEFAULT_POSTHOG_URL = "http://host.docker.internal:8010"
# 8010 is the bin/start default for dev. Override with --posthog-url if your
# local app binds elsewhere.


class Command(BaseCommand):
    help = (
        "Launch a PostHog sandbox that runs the query-performance autoresearch smoke test "
        "against SELECT 1 via the token-gated proxy endpoint."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--repository",
            default="PostHog/posthog",
            help="GitHub repository to clone into the sandbox (default: PostHog/posthog)",
        )
        parser.add_argument(
            "--branch",
            default="master",
            help="Branch to check out (default: master). Use your feature branch to test local changes.",
        )
        parser.add_argument(
            "--posthog-url",
            default=_DEFAULT_POSTHOG_URL,
            help=(
                "PostHog app URL as seen from inside the sandbox. Docker sandboxes reach the host "
                "via host.docker.internal. Defaults to %(default)s."
            ),
        )
        parser.add_argument(
            "--cluster",
            choices=("test", "prod"),
            default="test",
            help="Which cluster the proxy should dispatch to (default: test).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Stream raw log lines instead of only agent messages.",
        )

    def handle(self, *args, **options):
        repository = options["repository"]
        branch = options["branch"]
        posthog_url = options["posthog_url"]
        cluster = options["cluster"]
        verbose = options["verbose"]

        team, user = _resolve_team_and_user()
        _assert_github_integration(team)

        scope = f"clickhouse_perf:{cluster}_read"
        self.stdout.write(f"Minting OAuth token for user={user.id} team={team.id} scope={scope}")
        token = create_oauth_access_token_for_user(user, team.id, scopes=[scope])

        anthropic_base_url = _resolve_anthropic_base_url(self.stdout.write)
        prompt = _build_prompt(
            posthog_url=posthog_url,
            token=token,
            cluster=cluster,
            anthropic_base_url=anthropic_base_url,
        )

        context = CustomPromptSandboxContext(
            team_id=team.id,
            user_id=user.id,
            repository=repository,
        )

        self.stdout.write(f"Repository: {repository} (branch: {branch})")
        self.stdout.write(f"Target cluster: {cluster}")
        self.stdout.write(f"Sandbox will reach PostHog at: {posthog_url}")
        self.stdout.write("")

        try:
            last_message, _ = asyncio.run(
                run_prompt(
                    prompt=prompt,
                    context=context,
                    branch=branch,
                    step_name="query_performance_smoke",
                    verbose=verbose,
                    output_fn=self.stdout.write,
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Sandbox run failed: {e}"))
            self.stdout.write(traceback.format_exc())
            raise

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(last_message)


def _resolve_team_and_user() -> tuple[Team, "object"]:
    team = Team.objects.select_related("organization").first()
    if not team:
        raise CommandError("No team found in local database")
    membership = OrganizationMembership.objects.filter(organization=team.organization).order_by("id").first()
    if not membership:
        raise CommandError(f"No users in organization '{team.organization.name}' (team {team.id})")
    return team, membership.user


def _assert_github_integration(team: Team) -> None:
    if not Integration.objects.filter(team=team, kind="github").first():
        raise CommandError(
            f"No GitHub integration found for team {team.id}. "
            "Set up a GitHub App installation first: go to /settings/integrations."
        )


def _resolve_anthropic_base_url(log) -> str | None:
    gateway = getattr(settings, "SANDBOX_LLM_GATEWAY_URL", None)
    if not gateway:
        log(
            "warning: SANDBOX_LLM_GATEWAY_URL unset; pi-coding-agent in the sandbox will not have "
            "a gateway to route through. Set SANDBOX_LLM_GATEWAY_URL=http://host.docker.internal:3308 "
            "in your .env."
        )
        return None
    return f"{gateway.rstrip('/')}/{LLM_GATEWAY_PRODUCT_SLUG}"


def _build_prompt(*, posthog_url: str, token: str, cluster: str, anthropic_base_url: str | None) -> str:
    """The prompt is intentionally directive.

    We want the agent to run exactly one command and report its output. There
    is no reasoning to do here — the smoke test is deterministic shell work
    that happens to also invoke the pi campaign internally.

    The same scoped OAuth token doubles as ``ANTHROPIC_API_KEY`` because the
    gateway's Anthropic route authenticates via ``x-api-key`` (see
    ``services/llm-gateway/src/llm_gateway/auth/service.py::extract_token``),
    and ``llm_gateway:read`` is in ``INTERNAL_SCOPES`` so it's auto-added.
    """
    env_block = [
        f"ANTHROPIC_API_KEY={token}",
    ]
    if anthropic_base_url:
        env_block.append(f"ANTHROPIC_BASE_URL={anthropic_base_url}")
    env_line = "env " + " ".join(env_block)

    return f"""\
You are running a query-performance autoresearch smoke test inside a fresh
PostHog sandbox. Your only job is to execute the command below and report
its output. Do not modify the command. Do not analyze. Do not improvise.

Run this command from the repository root:

  {env_line} \\
      python3 products/query_performance_ai/scripts/run_campaign.py \\
      --posthog-url {posthog_url} \\
      --posthog-token {token} \\
      --cluster {cluster}

When the command exits, report:

  1. The exit code.
  2. The full stdout and stderr.
  3. A short one-line verdict: "PASS" if exit code was 0, else "FAIL".
"""
