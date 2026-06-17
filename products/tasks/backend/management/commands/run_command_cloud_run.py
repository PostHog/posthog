from __future__ import annotations

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import Integration, Team, User
from posthog.models.integration import GitHubIntegration

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.command_run import constants
from products.tasks.backend.temporal.command_run.activities import open_signed_pr
from products.tasks.backend.temporal.process_task.utils import RunSource


class Command(BaseCommand):
    help = (
        "Run a non-agent command cloud run end-to-end against a real repo using the local sandbox, "
        "bypassing Temporal. Provisions a sandbox, clones the repo, runs the command, then opens a PR "
        "backed by a GitHub-signed commit and prints the PR URL. DEBUG only."
    )

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="Team ID")
        parser.add_argument("--user-id", type=int, help="User ID (defaults to the first team member)")
        parser.add_argument("--repository", default="posthog/hedgebox", help="GitHub repository (owner/repo)")
        parser.add_argument(
            "--kind",
            default=constants.DEFAULT_COMMAND_RUN_KIND,
            choices=list(constants.COMMAND_RUN_WORKFLOWS.keys()),
            help="Which command cloud run to mimic. Named kinds run a canned command.",
        )
        parser.add_argument("--command", help="Command to run (for the generic 'command' kind)")
        parser.add_argument("--pr-title", help="Pull request title (generic kind)")
        parser.add_argument("--pr-body", default="", help="Pull request body (generic kind)")
        parser.add_argument("--base-branch", help="Base branch for the PR (defaults to repo default)")
        parser.add_argument("--github-token", help="GitHub token (falls back to the team integration)")
        parser.add_argument("--no-cleanup", action="store_true", help="Don't soft-delete the test task afterwards")
        parser.add_argument("--keep-sandbox", action="store_true", help="Don't destroy the sandbox afterwards")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("run_command_cloud_run only runs with DEBUG=1")

        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} not found")

        user = self._resolve_user(team, options.get("user_id"))
        repository = options["repository"]
        org, _, repo = repository.partition("/")
        if not org or not repo:
            raise CommandError("Repository must be in 'owner/repo' format")

        kind = options["kind"]
        if kind == constants.DEFAULT_COMMAND_RUN_KIND:
            command = options.get("command") or constants.APPEND_README_COMMAND
            pr_title = options.get("pr_title") or "Automated change"
            pr_body = options.get("pr_body") or ""
        else:
            # Named leaf: mirror the hardcoded hooks (currently only append_readme).
            command = constants.APPEND_README_COMMAND
            pr_title = constants.APPEND_README_PR_TITLE
            pr_body = constants.APPEND_README_PR_BODY

        github_integration = self._resolve_github_integration(team, org)
        github_token = options.get("github_token") or (github_integration.sensitive_config or {}).get("access_token")

        task = Task.objects.create(
            team=team,
            created_by=user,
            title=f"Command cloud run: {kind}",
            description=command,
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=github_integration,
            repository=repository,
        )
        task_run = task.create_run(
            extra_state={
                "run_source": RunSource.CLOUD_RUN.value,
                "command_run_kind": kind,
                "command": command,
                "pr_title": pr_title,
                "pr_body": pr_body,
                "base_branch": options.get("base_branch"),
            }
        )
        branch = f"cloud-run/{task_run.id}"
        self.stdout.write(f"Created task {task.id}, run {task_run.id} (kind={kind}, repo={repository})")

        sandbox = None
        try:
            # Deliberately mirrors BaseCloudRunWorkflow's lifecycle (provision → clone → run → open PR)
            # inline so it runs without a Temporal worker. Keep in sync with command_run/workflow.py.
            sandbox = Sandbox.create(
                SandboxConfig(
                    name=f"command-run-{task_run.id}",
                    template=SandboxTemplate.DEFAULT_BASE,
                    environment_variables={"GITHUB_TOKEN": github_token or "", "GH_TOKEN": github_token or ""},
                )
            )
            self.stdout.write(f"Sandbox created: {sandbox.id}")

            clone_result = sandbox.clone_repository(repository, github_token=github_token or "")
            if clone_result.exit_code != 0:
                raise CommandError(f"Failed to clone {repository}: {clone_result.stderr[:500]}")

            full_command = f"cd /tmp/workspace/repos/{org.lower()}/{repo.lower()} && {command}"
            self.stdout.write(f"Running command: {command}")
            stream = sandbox.execute_stream(full_command, timeout_seconds=30 * 60)
            for line in stream.iter_stdout():
                self.stdout.write(f"  | {line.rstrip()}")
            result = stream.wait()
            if result.exit_code != 0:
                raise CommandError(f"Command exited with status {result.exit_code}")

            github = GitHubIntegration(github_integration)
            if github.access_token_expired():
                github.refresh_access_token()
            pr = open_signed_pr(
                sandbox,
                github,
                repository=repository,
                branch=branch,
                base_branch=options.get("base_branch"),
                commit_headline=pr_title,
                pr_title=pr_title,
                pr_body=pr_body,
            )

            task_run.status = TaskRun.Status.COMPLETED
            task_run.save(update_fields=["status", "updated_at"])

            if not pr.created_pr:
                self.stdout.write(self.style.WARNING("Command left the repo clean — no PR opened"))
                return

            output = TaskRun.update_output_atomic(task_run.id, {"pr_url": pr.pr_url, "commit_sha": pr.commit_sha})
            self.stdout.write(self.style.SUCCESS(f"Opened PR: {pr.pr_url}"))
            self.stdout.write(f"Run output: {json.dumps(output)}")
        finally:
            if sandbox and not options["keep_sandbox"]:
                sandbox.destroy()
                self.stdout.write("Sandbox destroyed")
            elif sandbox:
                self.stdout.write(self.style.WARNING(f"Sandbox kept alive: {sandbox.id}"))
            if not options["no_cleanup"]:
                task.soft_delete()
                self.stdout.write("Test task cleaned up")

    def _resolve_github_integration(self, team: Team, owner: str) -> Integration:
        """Find a connected GitHub App installation for `owner`, or fail with a clear message.

        The PR is opened via the GitHub API, which needs a real installation (account name +
        access token) — not a placeholder row — so we validate up front rather than crashing
        deep in the GitHub client.
        """
        integrations = Integration.objects.filter(team=team, kind="github")
        if not integrations:
            raise CommandError(
                "This team has no connected GitHub integration. Connect the GitHub App from "
                "Settings → Linked accounts (with access to the target repo) before running a command cloud run."
            )
        for integration in integrations:
            account_name = (integration.config or {}).get("account", {}).get("name")
            access_token = (integration.sensitive_config or {}).get("access_token")
            if isinstance(account_name, str) and account_name and access_token:
                if account_name.lower() == owner.lower():
                    return integration
        raise CommandError(
            f"No connected GitHub App installation for '{owner}' was found for this team. "
            "Connect the GitHub App for that org from Settings → Linked accounts, or pass a "
            "--repository owned by an already-connected installation."
        )

    def _resolve_user(self, team: Team, user_id: int | None) -> User:
        if user_id is not None:
            user = User.objects.filter(id=user_id).first()
            if user is None:
                raise CommandError(f"User {user_id} not found")
            return user
        user = User.objects.filter(organization_membership__organization=team.organization).first()
        if user is None:
            raise CommandError(f"No user found for team {team.id}'s organization; pass --user-id")
        return user
