import json
import time
import base64
import secrets
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.models.team import Team
from posthog.utils import initialize_self_capture_api_token

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ...adapters.command_tag import CommandTagAdapter
from ...adapters.repo_merge import pull_request_dedupe_id
from ...facade.contracts import AdapterVerdict, DocsCommandRequest, DocsRequest
from ...facade.enums import DocsChangeKind
from ...feature_flags import AGENT_LAUNCH_FLAG, OPEN_PULL_REQUESTS_FLAG, is_team_flag_enabled
from ...logic import intake
from ...logic.launch import start_writer
from ...logic.pull_requests import LINK_BACK_START, docs_github, open_writer_pull_requests, source_repository_github
from ...logic.records import (
    HEAD_BRANCH_STATE_KEY,
    PULL_REQUEST_FAILURE_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    WriterPullRequest,
    pull_request_json,
)
from ...logic.routing import route_request
from ...logic.server_commit import docs_branch_head
from ...logic.writer_change import WRITER_CHANGE_ARTIFACT_NAME, writer_change_artifact
from ...settings import WriterSettings, writer_settings

PRODUCTION_DOCS_REPOSITORY = "posthog/posthog.com"
SCRATCH_PAGE_NAME = "knowledge-writer-smoke-test.mdx"
UNREACHABLE_PULL_REQUEST_FLOOR = 900_000_000
GITHUB_FAILURES = (GitHubIntegrationError, GitHubRateLimitError)
AGENT_POLL_INTERVAL_SECONDS = 15
SCRATCH_PUBLISH_TIMEOUT_SECONDS = 300
SMOKE_NOTE = "Knowledge writer smoke test."
SMOKE_REQUESTER = "knowledge-writer-smoke-test"


class Command(BaseCommand):
    help = (
        "Open a draft docs pull request on a scratch docs repository through the server commit, check it, and clean up."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--repo", required=True, help="Scratch docs repository as owner/name, never PostHog/posthog.com"
        )
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--installation-id", help="GitHub App installation to connect when the team has none for the repo owner"
        )
        parser.add_argument("--section", default="session-replay", help="Docs section the request targets")
        parser.add_argument(
            "--with-agent",
            metavar="SOURCE_PULL_REQUEST_URL",
            help="Run the real writer agent for a merged pull request whose change the section's docs lack",
        )
        parser.add_argument("--agent-timeout-minutes", type=int, default=240)

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("This command only runs with DEBUG=1")
        repository: str = options["repo"]
        if repository.lower() == PRODUCTION_DOCS_REPOSITORY:
            raise CommandError("Refusing to run against PostHog/posthog.com; use a scratch fork")
        team = Team.objects.filter(id=options["team_id"]).first()
        if team is None:
            raise CommandError(f"Team {options['team_id']} does not exist")
        writer = writer_settings()
        if writer is None or writer.team_id != team.id or writer.docs_repository.lower() != repository.lower():
            raise CommandError(
                "Set KNOWLEDGE_WRITER_TEAM_ID, KNOWLEDGE_WRITER_USER_ID and KNOWLEDGE_WRITER_DOCS_REPOSITORY "
                "to this team and repository"
            )
        if not is_team_flag_enabled(OPEN_PULL_REQUESTS_FLAG, team):
            raise CommandError(f"Turn the {OPEN_PULL_REQUESTS_FLAG} flag on at 100% for team {team.id}")
        github = connected_github(team.id, repository, options["installation_id"])
        section: str = options["section"]
        smoke_id = secrets.token_hex(4)
        source_url: str | None = options["with_agent"]
        branches: list[str] = []
        try:
            opened = (
                run_agent_request(
                    github, writer, team, section, source_url, smoke_id, options["agent_timeout_minutes"], branches
                )
                if source_url
                else run_scratch_request(github, writer, team, section, smoke_id, branches)
            )
            failures = check_pull_request(github, repository, opened)
        finally:
            cleanup_problems = clean_up(github, writer, repository, branches)
            for problem in cleanup_problems:
                self.stderr.write(f"CLEANUP FAILED {problem}")
        failures += cleanup_problems
        for failure in failures:
            self.stderr.write(f"FAIL {failure}")
        if failures:
            raise CommandError(f"{len(failures)} check(s) failed on {opened.url}")
        self.stdout.write(f"PASS draft pull request {opened.url} opened from a server commit, closed and cleaned up")


def connected_github(team_id: int, repository: str, installation_id: str | None) -> GitHubIntegration:
    owner = repository.split("/", 1)[0]
    github = docs_github(team_id, owner, priority=Priority.CRITICAL)
    if github is None and installation_id:
        GitHubIntegration.integration_from_installation_id(installation_id, team_id)
        github = docs_github(team_id, owner, priority=Priority.CRITICAL)
    if github is None:
        raise CommandError(f"Team {team_id} has no GitHub integration for {owner}; pass --installation-id")
    return github


def run_scratch_request(
    github: GitHubIntegration, writer: WriterSettings, team: Team, section: str, smoke_id: str, branches: list[str]
) -> WriterPullRequest:
    request = smoke_request(section, unreachable_source(writer.user_id), smoke_id)
    routing = route_request(request, team_id=team.id, github=source_repository_github(team.id))
    base_sha = docs_branch_head(github, writer.docs_repository)
    if base_sha is None:
        raise CommandError(f"Could not read the default branch head of {writer.docs_repository}")
    task_id = start_writer(request, routing, team=team, writer=writer, base_sha=base_sha, start_workflow=False)
    head_branch = tasks_facade.read_task_state_entry(task_id, team.id, HEAD_BRANCH_STATE_KEY)
    if not isinstance(head_branch, str):
        raise CommandError(f"Task {task_id} was issued no docs branch")
    branches.append(head_branch)
    page = f"Knowledge writer smoke test on {head_branch}.\n".encode()
    change = {
        "written": {f"contents/docs/{section}/{SCRATCH_PAGE_NAME}": base64.b64encode(page).decode()},
        "deleted": [],
    }
    for run_id in tasks_facade.list_task_run_ids(task_id, team.id):
        tasks_facade.upload_task_run_artifacts(
            run_id,
            task_id,
            team.id,
            artifacts=[
                {
                    "name": WRITER_CHANGE_ARTIFACT_NAME,
                    "type": "output",
                    "source": "agent_output",
                    "content_type": "application/json",
                    "content_bytes": json.dumps(change).encode(),
                }
            ],
        )
        tasks_facade.update_task_run(run_id, task_id, team.id, validated_data={"status": "completed"})
    deadline = time.monotonic() + SCRATCH_PUBLISH_TIMEOUT_SECONDS
    return wait_for_pull_request(task_id, team.id, deadline)


def merged_source(github: GitHubIntegration, source_url: str, requested_by_user_id: int) -> DocsCommandRequest:
    pull_request = github.get_pull_request_from_url(source_url)
    if not pull_request.get("success"):
        raise CommandError(f"Could not read {source_url}: {pull_request.get('error')}")
    # The agent writes no change for a source it cannot verify, so an unmerged one burns a full run.
    if not pull_request.get("merged"):
        raise CommandError(f"{source_url} is not merged")
    return DocsCommandRequest(
        repository=pull_request["repository"],
        pull_request_number=pull_request["number"],
        note=SMOKE_NOTE,
        requested_by=SMOKE_REQUESTER,
        requested_by_user_id=requested_by_user_id,
    )


def unreachable_source(requested_by_user_id: int) -> DocsCommandRequest:
    source_number = UNREACHABLE_PULL_REQUEST_FLOOR + secrets.randbelow(UNREACHABLE_PULL_REQUEST_FLOOR)
    return DocsCommandRequest(
        repository="PostHog/posthog",
        pull_request_number=source_number,
        note=SMOKE_NOTE,
        requested_by=SMOKE_REQUESTER,
        requested_by_user_id=requested_by_user_id,
    )


def smoke_verdict(section: str, source: DocsCommandRequest, smoke_suffix: str) -> AdapterVerdict:
    return AdapterVerdict(
        source=CommandTagAdapter.source,
        subject_id=pull_request_dedupe_id(source.repository, source.pull_request_number),
        needs_docs=True,
        reason="requested",
        request=smoke_request(section, source, smoke_suffix),
    )


def smoke_request(section: str, source: DocsCommandRequest, smoke_suffix: str) -> DocsRequest:
    source_url = source_pull_request_url(source)
    return DocsRequest(
        source=CommandTagAdapter.source,
        source_url=source_url,
        evidence=f"Pull request {source_url}.",
        change_kind=DocsChangeKind.UPDATE,
        suggested_page_urls=(f"https://posthog.com/docs/{section}",),
        trigger_instructions=source.note,
        dedupe_id=f"knowledge_writer:command_tag:smoke-{smoke_suffix}",
        requested_by=source.requested_by,
        requested_by_user_id=source.requested_by_user_id,
    )


def source_pull_request_url(source: DocsCommandRequest) -> str:
    return f"https://github.com/{source.repository}/pull/{source.pull_request_number}"


def run_agent_request(
    github: GitHubIntegration,
    writer: WriterSettings,
    team: Team,
    section: str,
    source_url: str,
    smoke_id: str,
    timeout_minutes: int,
    branches: list[str],
) -> WriterPullRequest:
    source = merged_source(github, source_url, writer.user_id)
    async_to_sync(initialize_self_capture_api_token)()
    deadline = time.monotonic() + timeout_minutes * 60
    outcome = intake.submit(smoke_verdict(section, source, smoke_id), team_id=team.id)
    if outcome.status == "shadow":
        raise CommandError(
            f"Intake ran in shadow mode: turn the {AGENT_LAUNCH_FLAG} flag on at 100% for team {team.id}"
        )
    if outcome.task_id is None or outcome.status != "started":
        raise CommandError(f"Intake answered {outcome.status} for {source_url}")
    head_branch = tasks_facade.read_task_state_entry(outcome.task_id, team.id, HEAD_BRANCH_STATE_KEY)
    if isinstance(head_branch, str):
        branches.append(head_branch)
    return wait_for_pull_request(outcome.task_id, team.id, deadline)


def wait_for_pull_request(task_id: UUID, team_id: int, deadline: float) -> WriterPullRequest:
    failure: object = None
    while time.monotonic() < deadline:
        stored = tasks_facade.read_task_state_entry(task_id, team_id, PULL_REQUEST_STATE_KEY)
        if isinstance(stored, dict):
            return pull_request_json.validate_python(stored)
        failure = tasks_facade.read_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY)
        if isinstance(failure, str):
            raise CommandError(f"Task {task_id} could not open its docs pull request: {failure}")
        for run_id in tasks_facade.list_task_run_ids(task_id, team_id):
            run = tasks_facade.get_task_run(run_id, team_id)
            if run is None:
                continue
            problem = ended_run_problem(run)
            if problem:
                raise CommandError(f"Writer run {run_id} on task {task_id} {problem}")
        time.sleep(AGENT_POLL_INTERVAL_SECONDS)
    raise CommandError(f"Timed out waiting for task {task_id} to record a pull request; last failure: {failure}")


def ended_run_problem(run: TaskRunDTO) -> str | None:
    if run.status in ("failed", "cancelled"):
        return f"ended {run.status}: {run.error_message}"
    if run.status == "completed" and writer_change_artifact(run.artifacts) is None:
        return f"completed without uploading {WRITER_CHANGE_ARTIFACT_NAME}"
    return None


def check_pull_request(
    github: GitHubIntegration,
    repository: str,
    opened: WriterPullRequest,
) -> list[str]:
    pull_request = github.api_request(
        "GET", f"/repos/{repository}/pulls/{opened.number}", endpoint="/repos/{owner}/{repo}/pulls/{pull_number}"
    ).json()
    body = pull_request.get("body") or ""
    checks = {
        "the pull request is a draft": pull_request.get("draft") is True,
        "the body has the link-back block": LINK_BACK_START in body,
        "the pull request changes files": pull_request.get("changed_files", 0) > 0,
    }
    return [description for description, passed in checks.items() if not passed]


def clean_up(github: GitHubIntegration, writer: WriterSettings, repository: str, branches: list[str]) -> list[str]:
    problems = close_smoke_pull_requests(github, writer, repository, branches)
    for branch in branches:
        problem = delete_branch(github, repository, branch)
        if problem:
            problems.append(problem)
    return problems


def close_smoke_pull_requests(
    github: GitHubIntegration, writer: WriterSettings, repository: str, branches: list[str]
) -> list[str]:
    try:
        open_pull_requests = open_writer_pull_requests(writer)
    except GITHUB_FAILURES as error:
        return [f"could not list pull requests to close on {repository}: {error}"]
    if open_pull_requests is None:
        return [f"could not list pull requests to close on {repository}"]
    problems: list[str] = []
    for pull_request in open_pull_requests:
        if pull_request.head_branch not in branches:
            continue
        try:
            closed = github.close_pull_request(repository, pull_request.number)
        except GITHUB_FAILURES as error:
            problems.append(f"could not close {pull_request.url}: {error}")
            continue
        if not closed.get("success"):
            problems.append(f"could not close {pull_request.url}: {closed.get('error')}")
    return problems


def delete_branch(github: GitHubIntegration, repository: str, branch: str) -> str | None:
    try:
        deleted = github.api_request(
            "DELETE", f"/repos/{repository}/git/refs/heads/{branch}", endpoint="/repos/{owner}/{repo}/git/refs/{ref}"
        )
    except GITHUB_FAILURES as error:
        return f"could not delete {branch}: {error}"
    # GitHub answers 422 for a ref that was never created, which a failed push leaves behind.
    if deleted.status_code not in (204, 422):
        return f"could not delete {branch}: {deleted.status_code} {deleted.text}"
    return None
