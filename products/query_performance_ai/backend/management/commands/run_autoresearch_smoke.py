"""Smoke test: run the autoresearch campaign in a fresh PostHog sandbox.

Provisions a Docker sandbox directly (no Claude-Code-in-the-middle), clones
the branch, invokes ``products/query_performance_ai/scripts/run_campaign.py``
with env vars for the proxy + LLM gateway, and live-streams pi's stdout to
the operator's terminal. On success, harvests workspace artifacts for
inspection.

A typical run completes in just under 3 minutes against the default
``SELECT sleep(0.5), 1`` smoke query. ``_CAMPAIGN_TIMEOUT_S`` below is the
hard upper bound (45 minutes, matching prod), not the expected duration.

This mirrors what the production Temporal activity
``run_autoresearch_campaign_in_sandbox`` does, minus Task/TaskRun/S3 plumbing,
so what you observe here is what the weekly job will observe.
"""

from __future__ import annotations

import sys
import json
import time
import uuid
import shlex
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.oauth import create_oauth_access_token_for_user

from products.query_performance_ai.backend.harvest import (
    LLM_GATEWAY_PRODUCT_SLUG,
    RunAutoresearchCampaignOutput,
    harvest_artifacts,
)
from products.tasks.backend.services.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class_for_backend
from products.tasks.backend.temporal.process_task.utils import get_github_token

_DEFAULT_POSTHOG_URL = "http://host.docker.internal:8000"
_DEFAULT_SMOKE_SQL_RELPATH = "products/query_performance_ai/data/smoke_test.sql"
# Git-ignored so runs don't pollute the working tree.
_SMOKE_OUTPUT_RELPATH = "products/query_performance_ai/data/smoke_output"
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
        explicit_branch: str | None = options["branch"]
        detected_branch = None if explicit_branch else _detect_current_branch()
        if not explicit_branch and detected_branch is None:
            self.stdout.write(self.style.WARNING("Could not detect current git branch; falling back to 'master'"))
        branch: str = explicit_branch or detected_branch or "master"
        posthog_url: str = options["posthog_url"]
        query_id: str | None = options["query_id"]
        keep_sandbox: bool = options["keep_sandbox"]

        team, user = _resolve_team_and_user()
        github_integration = _get_github_integration(team)
        _check_branch_on_remote(branch, self.stdout.write)

        sql = _load_sql_from_file(options["sql_file"])

        # Mint two SEPARATELY scoped tokens rather than one token holding
        # both scopes. pi runs inside a sandbox with access to both env vars,
        # so a prompt injection that makes pi echo `process.env` leaks
        # whichever token it dumps. Splitting means a leak of the
        # Anthropic-side token doesn't hand the attacker CH proxy access,
        # and a leak of the CH proxy token doesn't hand them gateway spend.
        # `include_internal_scopes=False` drops the auto-union so
        # `task:write` etc. never land on an LLM-held token.
        self.stdout.write(
            f"Minting two OAuth tokens for user={user.id} team={team.id}: "
            "proxy scope clickhouse_test_cluster_perf:test_read, gateway scope llm_gateway:read"
        )
        proxy_token = create_oauth_access_token_for_user(
            user,
            team.id,
            scopes=["clickhouse_test_cluster_perf:test_read"],
            include_internal_scopes=False,
        )
        gateway_token = create_oauth_access_token_for_user(
            user,
            team.id,
            scopes=["llm_gateway:read"],
            include_internal_scopes=False,
        )

        github_token = get_github_token(github_integration.id)
        if not github_token:
            raise CommandError(
                f"Could not mint GitHub token from integration {github_integration.id}. "
                "Reinstall the GitHub App from /settings/integrations."
            )

        anthropic_base_url = _resolve_anthropic_base_url(self.stdout.write)

        self.stdout.write(f"Repository: {repository} (branch: {branch})")
        self.stdout.write(f"Sandbox will reach PostHog at: {posthog_url}")
        self.stdout.write(f"SQL under test ({len(sql)} bytes):")
        self.stdout.write(_truncate(sql, 400))
        self.stdout.write("")

        sandbox_name = f"autoresearch-smoke-{uuid.uuid4()}"
        config = SandboxConfig(
            name=sandbox_name,
            template=SandboxTemplate.PI_BASE,
            default_execution_timeout_seconds=_CAMPAIGN_TIMEOUT_S,
            metadata={"purpose": "autoresearch-smoke"},
        )

        start = time.monotonic()

        def write(msg: str) -> None:
            self.stdout.write(f"[+{time.monotonic() - start:6.1f}s] {msg}")

        # Always local Docker — Modal would need auth + a real image push.
        sandbox_cls = get_sandbox_class_for_backend("docker")

        write("Provisioning sandbox…")
        sandbox = sandbox_cls.create(config)

        try:
            write(f"Sandbox {sandbox.id} up. Cloning {repository}@{branch} (shallow, target branch only)…")
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"
            org_path = f"/tmp/workspace/repos/{org}"
            repo_url = f"https://github.com/{org}/{repo}.git"

            # Hand git the token via `.netrc` rather than embedding it in the
            # clone URL — the URL form would leave the token in the shell
            # command's argv (readable from /proc/<pid>/cmdline by anything
            # else running in the sandbox). `write_file` pipes the bytes via
            # stdin so the token never lands in argv, and the trap deletes the
            # credential on exit (clone success or failure).
            netrc_contents = f"machine github.com\nlogin x-access-token\npassword {github_token}\n"
            sandbox.write_file("/root/.netrc", netrc_contents.encode())
            # `sandbox.clone_repository` always clones the default branch first;
            # we only need the target branch, so skip that round trip.
            clone_cmd = (
                "trap 'rm -f /root/.netrc' EXIT && "
                "chmod 600 /root/.netrc && "
                f"rm -rf {shlex.quote(repo_path)} && "
                f"mkdir -p {shlex.quote(org_path)} && "
                f"cd {shlex.quote(org_path)} && "
                f"git clone --depth 1 --single-branch --branch {shlex.quote(branch)} "
                f"{shlex.quote(repo_url)} {shlex.quote(repo)}"
            )
            clone_result = sandbox.execute(clone_cmd, timeout_seconds=5 * 60)
            if clone_result.exit_code != 0:
                raise CommandError(
                    f"git clone failed (exit {clone_result.exit_code}):\n{(clone_result.stderr or '')[-2000:]}"
                )

            env_values: dict[str, str] = {
                "POSTHOG_URL": posthog_url,
                "POSTHOG_OAUTH_TOKEN": proxy_token,
                "CAMPAIGN_SQL": sql,
            }
            if query_id:
                env_values["CAMPAIGN_QUERY_ID"] = query_id
            if anthropic_base_url:
                env_values["ANTHROPIC_BASE_URL"] = anthropic_base_url
                env_values["ANTHROPIC_API_KEY"] = gateway_token

            # Write env vars into a file inside the sandbox and `set -a;
            # source`-them rather than putting them on argv. The token values
            # would otherwise end up in shell history / `/proc/*/cmdline` /
            # docker_sandbox.py's debug-log line, which CodeQL flags as a
            # clear-text credential leak even inside a single-tenant sandbox.
            # `sandbox.write_file` pipes via stdin so no values touch argv.
            env_file = "/tmp/autoresearch-campaign.env"
            env_contents = "".join(f"{name}={shlex.quote(value)}\n" for name, value in env_values.items())
            sandbox.write_file(env_file, env_contents.encode())
            # execute_stream only iterates stdout; merge stderr so the operator
            # sees run_campaign.py's progress markers alongside pi's output.
            command = (
                f"cd {shlex.quote(repo_path)} && "
                f"trap 'rm -f {shlex.quote(env_file)}' EXIT && "
                f"chmod 600 {shlex.quote(env_file)} && "
                f"set -a && . {shlex.quote(env_file)} && set +a && "
                f"python3 products/query_performance_ai/scripts/run_campaign.py 2>&1"
            )

            write("Running run_campaign.py (live stdout below)…")
            self.stdout.write("-" * 60)
            stream = sandbox.execute_stream(command, timeout_seconds=_CAMPAIGN_TIMEOUT_S)
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
            output = harvest_artifacts(
                sandbox,
                original_sql=sql,
                query_id=query_id or "smoke",
                campaign_stdout_tail=(result.stdout or "")[-4000:],
            )

            output_dir = Path(settings.BASE_DIR) / _SMOKE_OUTPUT_RELPATH
            _write_artifacts_to_disk(output, output_dir)
            write(f"Artifacts written to {output_dir}")

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
                f"warning: local '{branch}' differs from origin/{branch} — the sandbox will "
                "clone origin's snapshot. `git push` to publish local commits, or `git pull` "
                "if origin is ahead."
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


def _resolve_team_and_user() -> tuple[Team, User]:
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
            "a gateway to route through. bin/start sets this for local dev — if you invoked the "
            "smoke another way, export it yourself."
        )
        return None
    return f"{gateway.rstrip('/')}/{LLM_GATEWAY_PRODUCT_SLUG}"


def _write_artifacts_to_disk(output: RunAutoresearchCampaignOutput, dest: Path) -> None:
    """Dump harvested campaign artifacts into a local directory.

    Wipes everything in ``dest`` except the checked-in ``.gitignore`` so each
    run starts clean. The dir itself is tracked (for the .gitignore) but its
    contents are ignored, so writing here does not dirty the working tree.
    """
    dest.mkdir(parents=True, exist_ok=True)
    for entry in dest.iterdir():
        if entry.name == ".gitignore":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    (dest / "original.sql").write_text(
        output.original_sql + "\n" if not output.original_sql.endswith("\n") else output.original_sql
    )
    if output.best_sql:
        (dest / "best.sql").write_text(
            output.best_sql + "\n" if not output.best_sql.endswith("\n") else output.best_sql
        )
    if output.baseline_metrics_json:
        (dest / "baseline_metrics.json").write_text(output.baseline_metrics_json)
    if output.best_metrics_json:
        (dest / "best_run_metrics.json").write_text(output.best_metrics_json)
    if output.last_run_json:
        (dest / "last_run.json").write_text(output.last_run_json)
    if output.operator_hunches:
        (dest / "operator_hunches.md").write_text(output.operator_hunches)
    if output.suggestions:
        (dest / "suggestions.md").write_text(output.suggestions)
    if output.campaign_stdout_tail:
        (dest / "campaign_stdout_tail.log").write_text(output.campaign_stdout_tail)

    _write_markdown_dir(dest / "lanes", output.lanes)
    _write_markdown_dir(dest / "hypotheses", output.hypotheses)
    _write_markdown_dir(dest / "reviews", output.reviews)

    # Canonical JSON for downstream tooling — saves re-parsing the filesystem.
    summary = {
        "query_id": output.query_id,
        "original_sql": output.original_sql,
        "best_sql": output.best_sql,
        "baseline_metrics_json": output.baseline_metrics_json,
        "best_run_metrics_json": output.best_metrics_json,
        "last_run_json": output.last_run_json,
        "lane_count": len(output.lanes),
        "hypothesis_count": len(output.hypotheses),
        "review_count": len(output.reviews),
    }
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))


def _write_markdown_dir(dest: Path, entries: list[tuple[str, str]]) -> None:
    if not entries:
        return
    dest.mkdir(parents=True, exist_ok=True)
    for name, contents in entries:
        (dest / name).write_text(contents)


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"… [truncated, {len(s)} total bytes]"
