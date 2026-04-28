"""Smoke: run the autoresearch campaign in a fresh local Docker sandbox.

Mirrors the production Temporal activity (minus Task/TaskRun/S3 plumbing).
Default ``SELECT sleep(0.5), 1`` query lands in under ~3 minutes.
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
from posthog.temporal.oauth import create_internal_oauth_access_token, create_oauth_access_token_for_user

from products.query_performance_ai.backend.harvest import (
    LLM_GATEWAY_PRODUCT_SLUG,
    RunAutoresearchCampaignOutput,
    harvest_artifacts,
)
from products.tasks.backend.services.sandbox import SandboxConfig, SandboxTemplate, get_sandbox_class_for_backend
from products.tasks.backend.temporal.process_task.utils import get_github_token

_DEFAULT_POSTHOG_URL = "http://host.docker.internal:8000"
_DEFAULT_SMOKE_SQL_RELPATH = "products/query_performance_ai/data/smoke_test.sql"
_SMOKE_OUTPUT_RELPATH = "products/query_performance_ai/data/smoke_output"  # gitignored
_CAMPAIGN_TIMEOUT_S = 45 * 60  # matches prod activity's CAMPAIGN_SCRIPT_TIMEOUT_S


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

        # Two tokens, each with one scope: a prompt-injection-induced env
        # dump leaking either token doesn't hand the attacker the other.
        # `include_internal_scopes=False` keeps `task:write` etc. off the
        # LLM-held token. The proxy token is user-less (the proxy rejects
        # team-scoped tokens); the gateway token is team-scoped because the
        # LLM gateway authorizes per team.
        self.stdout.write(
            f"Minting two OAuth tokens (gateway under user={user.id} team={team.id}): "
            "proxy scope clickhouse_test_cluster_perf:read, gateway scope llm_gateway:read"
        )
        proxy_token = create_internal_oauth_access_token(["clickhouse_test_cluster_perf:read"])
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

        sql_preview = sql if len(sql) <= 400 else sql[:400] + f"… [truncated, {len(sql)} total bytes]"
        self.stdout.write(f"Repository: {repository} (branch: {branch})")
        self.stdout.write(f"Sandbox will reach PostHog at: {posthog_url}")
        self.stdout.write(f"SQL under test ({len(sql)} bytes):\n{sql_preview}\n")

        sandbox_name = f"autoresearch-smoke-{uuid.uuid4()}"
        config = SandboxConfig(
            name=sandbox_name,
            # PI_BASE (#55821) will replace install_pi_toolchain's ~30-90s.
            template=SandboxTemplate.DEFAULT_BASE,
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

            # `.netrc` keeps the token out of argv (i.e. /proc/*/cmdline).
            netrc_contents = f"machine github.com\nlogin x-access-token\npassword {github_token}\n"
            sandbox.write_file("/root/.netrc", netrc_contents.encode())
            # `sandbox.clone_repository` would clone the default branch first,
            # which we'd just throw away.
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

            # File-then-source keeps token values off argv / shell history /
            # docker_sandbox.py's debug-log line; CodeQL flags any of those as
            # a clear-text credential leak.
            env_file = "/tmp/autoresearch-campaign.env"
            env_contents = "".join(f"{name}={shlex.quote(value)}\n" for name, value in env_values.items())
            sandbox.write_file(env_file, env_contents.encode())
            # 2>&1 — execute_stream only iterates stdout.
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
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCampaign {output.query_id}: best.sql, summary.json, and {len(output.lanes)} lane / "
                    f"{len(output.hypotheses)} hypothesis / {len(output.reviews)} review note(s) under {output_dir}"
                )
            )
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
    """The sandbox clones from origin, so a missing branch fails the smoke
    silently mid-campaign; fail loud here instead. Local-vs-origin SHA
    drift is only a warning."""
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
    """Wipe everything but the checked-in `.gitignore` so each run starts clean."""
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
    if output.out_of_scope_suggestions:
        (dest / "out-of-scope-suggestions.md").write_text(output.out_of_scope_suggestions)
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
