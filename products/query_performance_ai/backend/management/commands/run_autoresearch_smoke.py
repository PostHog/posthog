"""Smoke test: run the autoresearch campaign in a fresh PostHog sandbox.

Provisions a Docker sandbox directly (no Claude-Code-in-the-middle), clones
the branch, invokes ``products/query_performance_ai/scripts/run_campaign.py``
with env vars for the proxy + LLM gateway, and live-streams pi's stdout to
the operator's terminal. On success, harvests workspace artifacts for
inspection.

This mirrors what the production Temporal activity
``run_autoresearch_campaign_in_sandbox`` does, minus Task/TaskRun/S3 plumbing,
so what you observe here is what the weekly job will observe.
"""

from __future__ import annotations

import sys
import time
import uuid
import shlex
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.tasks.backend.services.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class_for_backend
from products.tasks.backend.temporal.process_task.activities.run_autoresearch_campaign import (
    LLM_GATEWAY_PRODUCT_SLUG,
    _harvest_artifacts,
)
from products.tasks.backend.temporal.process_task.utils import get_github_token

_DEFAULT_POSTHOG_URL = "http://host.docker.internal:8000"
# Default SQL file, relative to the repo root. Checked into the repo so the
# query under test travels with the code — iterating the smoke means editing
# this file (or passing ``--sql-file`` with a throwaway path).
_DEFAULT_SMOKE_SQL_RELPATH = "products/query_performance_ai/data/smoke_test.sql"
# 45 minutes: matches the prod activity's CAMPAIGN_SCRIPT_TIMEOUT_S.
_CAMPAIGN_TIMEOUT_S = 45 * 60


class Command(BaseCommand):
    help = (
        "Provision a local Docker sandbox and run the query-performance autoresearch "
        "campaign against the SQL in --sql-file. Streams pi's stdout live."
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
                "Branch to check out in the sandbox. Defaults to the current local git branch "
                "(falls back to 'master' if detection fails). Must exist on origin — the sandbox "
                "clones from there."
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
            "--sql-file",
            default=_DEFAULT_SMOKE_SQL_RELPATH,
            help=(
                "Path (relative to the repo root or absolute) to a .sql file whose contents are "
                "handed to run_campaign.py as CAMPAIGN_SQL. Defaults to %(default)s."
            ),
        )
        parser.add_argument(
            "--query-id",
            default=None,
            help=("Campaign identifier. Passed as CAMPAIGN_QUERY_ID. Defaults to run_campaign.py's fallback."),
        )
        parser.add_argument(
            "--keep-sandbox",
            action="store_true",
            help=(
                "Do not destroy the sandbox at the end. Useful for post-mortem inspection — "
                "``docker exec -it <container> bash`` into it to poke at the workspace."
            ),
        )

    def handle(self, *args, **options):
        repository: str = options["repository"]
        branch: str = options["branch"] or _detect_current_branch() or "master"
        posthog_url: str = options["posthog_url"]
        cluster: str = options["cluster"]
        query_id: str | None = options["query_id"]
        keep_sandbox: bool = options["keep_sandbox"]

        team, user = _resolve_team_and_user()
        github_integration = _get_github_integration(team)
        _check_branch_on_remote(branch, self.stdout.write)

        sql = _load_sql_from_file(options["sql_file"])

        scope = f"clickhouse_perf:{cluster}_read"
        self.stdout.write(f"Minting OAuth token for user={user.id} team={team.id} scope={scope}")
        token = create_oauth_access_token_for_user(user, team.id, scopes=[scope])

        github_token = get_github_token(github_integration.id)
        if not github_token:
            raise CommandError(
                f"Could not mint GitHub token from integration {github_integration.id}. "
                "Reinstall the GitHub App from /settings/integrations."
            )

        anthropic_base_url = _resolve_anthropic_base_url(self.stdout.write)

        self.stdout.write(f"Repository: {repository} (branch: {branch})")
        self.stdout.write(f"Target cluster: {cluster}")
        self.stdout.write(f"Sandbox will reach PostHog at: {posthog_url}")
        self.stdout.write(f"SQL under test ({len(sql)} bytes):")
        self.stdout.write(_truncate(sql, 400))
        self.stdout.write("")

        sandbox_name = f"autoresearch-smoke-{uuid.uuid4()}"
        config = SandboxConfig(
            name=sandbox_name,
            template=SandboxTemplate.DEFAULT_BASE,
            default_execution_timeout_seconds=_CAMPAIGN_TIMEOUT_S,
            metadata={"purpose": "autoresearch-smoke"},
        )

        start = time.monotonic()

        def write(msg: str) -> None:
            self.stdout.write(f"[+{time.monotonic() - start:6.1f}s] {msg}")

        # The smoke always uses the local Docker backend — it's a dev tool,
        # and routing through Modal would require Modal auth + push a real
        # image. If you have a reason to override, set SANDBOX_PROVIDER=docker
        # in your .env and the default resolver would pick it up, but this
        # explicit call means the smoke works regardless of env.
        sandbox_cls = get_sandbox_class_for_backend("docker")

        write("Provisioning sandbox…")
        sandbox = sandbox_cls.create(config)

        try:
            write(f"Sandbox {sandbox.id} up. Cloning {repository}@{branch}…")
            clone_result = sandbox.clone_repository(repository, github_token=github_token, shallow=True)
            if clone_result.exit_code != 0:
                raise CommandError(
                    f"git clone failed (exit {clone_result.exit_code}):\n{(clone_result.stderr or '')[-2000:]}"
                )

            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

            write(f"Checking out branch {branch}…")
            checkout = sandbox.execute(
                f"cd {shlex.quote(repo_path)} && "
                f"git fetch --depth 1 origin -- {shlex.quote(branch)} && "
                f"git checkout -B {shlex.quote(branch)} FETCH_HEAD",
                timeout_seconds=5 * 60,
            )
            if checkout.exit_code != 0:
                raise CommandError(
                    f"branch checkout failed (exit {checkout.exit_code}):\n{(checkout.stderr or '')[-2000:]}"
                )

            env_values: dict[str, str] = {
                "POSTHOG_URL": posthog_url,
                "POSTHOG_OAUTH_TOKEN": token,
                "POSTHOG_CLUSTER": cluster,
                "CAMPAIGN_SQL": sql,
            }
            if query_id:
                env_values["CAMPAIGN_QUERY_ID"] = query_id
            if anthropic_base_url:
                env_values["ANTHROPIC_BASE_URL"] = anthropic_base_url
                env_values["ANTHROPIC_API_KEY"] = token

            env_assignments = " ".join(f"{name}={shlex.quote(value)}" for name, value in env_values.items())
            # 2>&1 merges stderr into stdout so execute_stream (which only iterates
            # stdout) picks up both. run_campaign.py writes its progress markers to
            # stderr; without merging, the operator sees only child-process stdout
            # and nothing between "baseline captured" and pi's final summary.
            command = (
                f"cd {shlex.quote(repo_path)} && "
                f"env {env_assignments} "
                f"python3 products/query_performance_ai/scripts/run_campaign.py 2>&1"
            )

            write("Running run_campaign.py (live stdout below)…")
            self.stdout.write("-" * 60)
            stream = sandbox.execute_stream(command, timeout_seconds=_CAMPAIGN_TIMEOUT_S)
            # Stream each line as it arrives — no batching, no agent mediation.
            # Pi's internal reasoning still only flushes at its own cadence
            # (whenever it writes to stdout) but now we see those writes in real time.
            for line in stream.iter_stdout():
                sys.stdout.write(line)
                sys.stdout.flush()
            result = stream.wait()
            self.stdout.write("-" * 60)

            if result.exit_code != 0:
                stderr_tail = (result.stderr or "")[-2000:]
                self.stdout.write(
                    self.style.ERROR(f"run_campaign.py exited {result.exit_code}\nstderr tail:\n{stderr_tail}")
                )
                raise CommandError(f"run_campaign.py exited {result.exit_code}")

            write("Campaign finished — harvesting artifacts…")
            output = _harvest_artifacts(
                sandbox,
                original_sql=sql,
                query_id=query_id or "smoke",
                campaign_stdout_tail=(result.stdout or "")[-4000:],
            )

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(self.style.SUCCESS("Campaign summary"))
            self.stdout.write(self.style.SUCCESS("=" * 60))
            self.stdout.write(f"query_id: {output.query_id}")
            self.stdout.write(f"original SQL:\n{output.original_sql}")
            self.stdout.write(f"best SQL:\n{output.best_sql}")
            self.stdout.write(f"baseline metrics: {output.baseline_metrics_json or '(missing)'}")
            self.stdout.write(f"best run metrics: {output.best_metrics_json or '(no runs)'}")
            self.stdout.write(
                f"lanes: {len(output.lanes)}; hypotheses: {len(output.hypotheses)}; reviews: {len(output.reviews)}"
            )
            if output.suggestions:
                self.stdout.write("")
                self.stdout.write("suggestions.md:")
                self.stdout.write(output.suggestions)
        finally:
            if keep_sandbox:
                self.stdout.write(
                    self.style.WARNING(
                        f"--keep-sandbox set; leaving {sandbox.id} running. Destroy manually when done:\n"
                        f"    docker stop {sandbox.id} && docker rm {sandbox.id}"
                    )
                )
            else:
                write(f"Destroying sandbox {sandbox.id}…")
                try:
                    sandbox.destroy()
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Sandbox destroy failed: {e}"))


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


def _check_branch_on_remote(branch: str, log) -> None:
    """Ensure the branch exists on origin — the sandbox clones from remote.

    A missing branch is a hard error: the sandbox will clone origin and try
    to check out the branch, fail silently, and the smoke would terminate
    with a confusing tail. Fail fast with a clear instruction instead.

    A local HEAD that diverges from origin is only a warning — the sandbox
    will just use origin's snapshot.
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
    if result.returncode != 0 or not result.stdout.strip():
        raise CommandError(
            f"branch '{branch}' does not exist on origin. The sandbox clones from origin, so "
            f"it cannot check out this branch. Push it first:\n"
            f"    git push -u origin {branch}\n"
            f"or rerun with --branch pointing at a branch that already exists on origin."
        )
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


def _load_sql_from_file(path_str: str) -> str:
    """Resolve ``path_str`` against the repo root (if relative) and read it."""
    path = Path(path_str)
    if not path.is_absolute():
        path = Path(settings.BASE_DIR) / path
    if not path.is_file():
        raise CommandError(
            f"--sql-file does not exist: {path}. Create the file or pass --sql-file with a different path."
        )
    content = path.read_text().strip()
    if not content:
        raise CommandError(f"--sql-file is empty: {path}. The campaign needs some SQL to optimize.")
    return content


def _resolve_team_and_user() -> tuple[Team, object]:
    team = Team.objects.select_related("organization").first()
    if not team:
        raise CommandError("No team found in local database")
    membership = OrganizationMembership.objects.filter(organization=team.organization).order_by("id").first()
    if not membership:
        raise CommandError(f"No users in organization '{team.organization.name}' (team {team.id})")
    return team, membership.user


def _get_github_integration(team: Team) -> Integration:
    integration = Integration.objects.filter(team=team, kind="github").first()
    if not integration:
        raise CommandError(
            f"No GitHub integration found for team {team.id}. "
            "Set up a GitHub App installation first: go to /settings/integrations."
        )
    return integration


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


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"… [truncated, {len(s)} total bytes]"
