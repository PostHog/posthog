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
import subprocess
import time
import traceback

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.custom_prompt_runner import (
    CustomPromptSandboxContext,
    _create_task_and_trigger,
    _poll_for_turn,
)
from products.tasks.backend.temporal.process_task.activities.run_autoresearch_campaign import (
    LLM_GATEWAY_PRODUCT_SLUG,
)

# How long between "still waiting" ticks when the sandbox has gone quiet.
# The underlying poller checks S3 every ~10s — shorter than that just echoes
# the poll interval back at the user, longer misses real stalls.
_IDLE_TICK_INTERVAL_S = 20.0


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
            default=None,
            help=(
                "Branch to check out in the sandbox. Defaults to the current local git branch, "
                "which is almost always what you want while iterating. Falls back to 'master' if "
                "detection fails."
            ),
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
        branch = options["branch"] or _detect_current_branch() or "master"
        posthog_url = options["posthog_url"]
        cluster = options["cluster"]
        verbose = options["verbose"]

        team, user = _resolve_team_and_user()
        _assert_github_integration(team)
        _warn_if_branch_not_on_remote(branch, self.stdout.write)

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
        if not verbose:
            self.stdout.write(
                "Tip: pass --verbose to stream every sandbox log line (including run_campaign.py stdout)."
            )
        self.stdout.write("")

        try:
            last_message = asyncio.run(
                self._run_with_progress(prompt, context, branch, verbose)
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Sandbox run failed: {e}"))
            self.stdout.write(traceback.format_exc())
            raise

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(last_message)

    async def _run_with_progress(
        self,
        prompt: str,
        context: CustomPromptSandboxContext,
        branch: str | None,
        verbose: bool,
    ) -> str:
        """Drive the sandbox run with timestamped output and an idle ticker.

        We split the two halves of ``run_prompt`` (task creation + polling)
        so we can print the Task/Run/Workflow IDs before polling starts —
        otherwise the user sees no output until the sandbox starts producing
        logs, which can take a minute on a fresh provision.
        """
        start = time.monotonic()
        last_activity = {"at": start}

        def write(line: str) -> None:
            elapsed = time.monotonic() - start
            self.stdout.write(f"[+{elapsed:6.1f}s] {line}")
            last_activity["at"] = time.monotonic()

        task, task_run = await _create_task_and_trigger(
            prompt,
            context,
            branch=branch,
            step_name="query_performance_smoke",
            origin_product="query_performance",
        )
        workflow_id = TaskRun.get_workflow_id(task.id, task_run.id)
        namespace = getattr(settings, "TEMPORAL_NAMESPACE", "default")
        write(f"Task created: id={task.id} run_id={task_run.id}")
        write(f"Temporal workflow id: {workflow_id}  (namespace: {namespace})")
        write(f"Temporal UI:  http://localhost:8233/namespaces/{namespace}/workflows/{workflow_id}")
        write(f"Django admin: /admin/tasks/task/{task.id}/change/")
        write("Polling S3 for sandbox logs (first lines can take ~60-90s while the sandbox provisions)...")

        ticker_task = asyncio.create_task(self._idle_ticker(start, last_activity))
        try:
            last_message, _full_log, _, _ = await _poll_for_turn(
                task_run,
                verbose=verbose,
                output_fn=write,
            )
        finally:
            ticker_task.cancel()
            try:
                await ticker_task
            except asyncio.CancelledError:
                pass

        return last_message

    async def _idle_ticker(self, start: float, last_activity: dict) -> None:
        """Emit a tick if no log line has arrived for ``_IDLE_TICK_INTERVAL_S``.

        Runs until cancelled. The poll interval in custom_prompt_runner is
        ~10s, so ticks at 20s+ idle genuinely mean nothing new has landed
        in S3 — usually the sandbox is still provisioning or pi is
        installing packages.
        """
        while True:
            await asyncio.sleep(_IDLE_TICK_INTERVAL_S / 2)
            idle = time.monotonic() - last_activity["at"]
            if idle >= _IDLE_TICK_INTERVAL_S:
                elapsed = time.monotonic() - start
                self.stdout.write(
                    f"[+{elapsed:6.1f}s] ... still waiting ({idle:.0f}s since last line)"
                )
                # Reset so we tick at the same cadence going forward rather than
                # immediately on the next iteration.
                last_activity["at"] = time.monotonic()


def _detect_current_branch() -> str | None:
    """Return the current git branch, or None if detection fails."""
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "branch", "--show-current"],
            check=False,
            text=True,
            capture_output=True,
            cwd=settings.BASE_DIR,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    branch = (result.stdout or "").strip()
    return branch or None


def _warn_if_branch_not_on_remote(branch: str, log) -> None:
    """Warn if the branch isn't on origin — the sandbox clones from remote.

    If the user iterated locally without pushing, the sandbox will clone an
    old snapshot of the branch (or 404 fetching it). Flagging this upfront
    saves a 60-second round trip through Temporal just to find out.
    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", "ls-remote", "--heads", "origin", branch],
            check=False,
            text=True,
            capture_output=True,
            cwd=settings.BASE_DIR,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return
    if result.returncode == 0 and result.stdout.strip():
        # Also check if local HEAD matches the remote — if not, warn that the
        # sandbox will see stale code.
        try:
            local = subprocess.run(  # noqa: S603
                ["git", "rev-parse", branch],
                check=False,
                text=True,
                capture_output=True,
                cwd=settings.BASE_DIR,
                timeout=5,
            )
            remote_sha = result.stdout.split()[0]
            if local.returncode == 0 and local.stdout.strip() != remote_sha:
                log(
                    f"warning: local '{branch}' is ahead/behind origin/{branch} — the sandbox "
                    "will clone origin's snapshot. `git push` if you want your latest changes."
                )
        except Exception:
            pass
        return
    log(
        f"warning: branch '{branch}' does not exist on origin. The sandbox will fail to check "
        f"it out. Run: git push -u origin {branch}"
    )


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
