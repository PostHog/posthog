import os
import json
import time
import base64
import asyncio
import secrets
from collections.abc import Callable
from urllib.parse import quote
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import requests
from asgiref.sync import async_to_sync
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.service import RPCError

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubInstallationAccessFetchError, GitHubIntegration, GitHubIntegrationError
from posthog.models.team import Team
from posthog.temporal.common.client import async_connect
from posthog.utils import absolute_uri, initialize_self_capture_api_token

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ...adapters.command_tag import CommandTagAdapter
from ...adapters.repo_merge import pull_request_dedupe_id
from ...facade.contracts import AdapterVerdict, DocsCommandRequest, DocsRequest
from ...facade.enums import DocsChangeKind
from ...feature_flags import AGENT_LAUNCH_FLAG, OPEN_PULL_REQUESTS_FLAG, WRITER_FLAG, team_flag_state
from ...logic import intake
from ...logic.launch import start_writer
from ...logic.pull_requests import (
    LINK_BACK_START,
    OpenPullRequestsUnavailable,
    docs_github,
    open_writer_pull_requests,
    source_repository_github,
)
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
from ...temporal.client import publish_workflow_id

PRODUCTION_DOCS_REPOSITORY = "posthog/posthog.com"
SCRATCH_PAGE_NAME = "knowledge-writer-smoke-test.mdx"
UNREACHABLE_PULL_REQUEST_FLOOR = 900_000_000
GITHUB_FAILURES = (GitHubIntegrationError, GitHubRateLimitError)
AGENT_POLL_INTERVAL_SECONDS = 15
SCRATCH_PUBLISH_TIMEOUT_SECONDS = 300
SMOKE_NOTE = "Knowledge writer smoke test."
SMOKE_REQUESTER = "knowledge-writer-smoke-test"
LOCAL_LLM_GATEWAY_LIVENESS_URL = "http://localhost:3308/_liveness"
PROBE_TIMEOUT_SECONDS = 3
LOCAL_SANDBOX_URLS = {
    "SELF_CAPTURE_HOST": "http://localhost:8010",
    "SANDBOX_API_URL": "http://localhost:8010",
    "SANDBOX_LLM_GATEWAY_URL": "http://host.docker.internal:3308",
}


@frozen
class MissingPrerequisite:
    name: str
    fix: str


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
        source_url: str | None = options["with_agent"]
        missing = missing_prerequisites(team, repository, needs_agent=source_url is not None)
        github = None if missing else connected_github(team.id, repository, options["installation_id"])
        if not missing and github is None:
            missing.append(
                MissingPrerequisite(
                    name=f"GitHub integration for {repository.split('/', 1)[0]}",
                    fix="install the dev GitHub App on the scratch fork and pass its --installation-id",
                )
            )
        for prerequisite in missing:
            self.stderr.write(f"MISSING {prerequisite.name}: {prerequisite.fix}")
        writer = writer_settings()
        if missing or writer is None or github is None:
            raise CommandError(f"{len(missing)} prerequisite(s) missing")
        section: str = options["section"]
        smoke_id = secrets.token_hex(4)
        branches: list[str] = []
        try:
            opened = (
                run_agent_request(
                    github,
                    writer,
                    team,
                    section,
                    source_url,
                    smoke_id,
                    options["agent_timeout_minutes"],
                    branches,
                    self.stdout.write,
                )
                if source_url
                else run_scratch_request(github, writer, team, section, smoke_id, branches, self.stdout.write)
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


def missing_prerequisites(team: Team, repository: str, *, needs_agent: bool) -> list[MissingPrerequisite]:
    flags = [WRITER_FLAG, OPEN_PULL_REQUESTS_FLAG, *([AGENT_LAUNCH_FLAG] if needs_agent else [])]
    missing = [*missing_writer_environment(team, repository), *missing_flags(team, flags)]
    temporal_problem = temporal_worker_problem()
    if temporal_problem:
        missing.append(temporal_problem)
    if needs_agent:
        missing += missing_agent_services()
    return missing


def missing_writer_environment(team: Team, repository: str) -> list[MissingPrerequisite]:
    expected = {
        "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
        "KNOWLEDGE_WRITER_DOCS_REPOSITORY": repository,
    }
    missing = [
        MissingPrerequisite(name=name, fix=f"export {name}={value}")
        for name, value in expected.items()
        if os.environ.get(name, "").lower() != value.lower()
    ]
    if not os.environ.get("KNOWLEDGE_WRITER_USER_ID", "").isdigit():
        missing.append(
            MissingPrerequisite(
                name="KNOWLEDGE_WRITER_USER_ID", fix="export KNOWLEDGE_WRITER_USER_ID=<id of a user in the team>"
            )
        )
    return missing


def missing_flags(team: Team, flags: list[str]) -> list[MissingPrerequisite]:
    states = {flag: team_flag_state(flag, team) for flag in flags}
    if all(state is None for state in states.values()):
        return [
            MissingPrerequisite(
                name="feature flags",
                fix=f"run bin/start-rust-service feature-flags, then create {', '.join(flags)} at 100% for team {team.id}",
            )
        ]
    return [
        MissingPrerequisite(name=f"{flag} flag", fix=f"create it if missing and turn it on at 100% for team {team.id}")
        for flag, state in states.items()
        if state is not True
    ]


def temporal_worker_problem() -> MissingPrerequisite | None:
    try:
        pollers = asyncio.run(asyncio.wait_for(task_queue_pollers(), PROBE_TIMEOUT_SECONDS))
    except (RPCError, OSError, RuntimeError, TimeoutError) as error:
        return MissingPrerequisite(
            name="Temporal server",
            fix=f"start the temporal docker compose profile ({error.__class__.__name__}: {error})",
        )
    if pollers == 0:
        return MissingPrerequisite(
            name=f"Temporal worker on {settings.VIDEO_EXPORT_TASK_QUEUE}",
            fix=f"python manage.py start_temporal_worker --task-queue {settings.VIDEO_EXPORT_TASK_QUEUE}",
        )
    return None


async def task_queue_pollers() -> int:
    client = await async_connect()
    described = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=client.namespace,
            task_queue=TaskQueue(name=settings.VIDEO_EXPORT_TASK_QUEUE),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    return len(described.pollers)


def missing_agent_services() -> list[MissingPrerequisite]:
    missing: list[MissingPrerequisite] = []
    try:
        requests.get(LOCAL_LLM_GATEWAY_LIVENESS_URL, timeout=PROBE_TIMEOUT_SECONDS).raise_for_status()
    except requests.RequestException as error:
        missing.append(
            MissingPrerequisite(
                name="LLM gateway",
                fix=f"run bin/start-llm-gateway with LLM_GATEWAY_DEBUG=true ({error.__class__.__name__})",
            )
        )
    if not os.environ.get("CODER"):
        return missing
    missing += [
        MissingPrerequisite(name=name, fix=f"export {name}={url} for every process on a Coder workspace")
        for name, url in LOCAL_SANDBOX_URLS.items()
        if os.environ.get(name) != url
    ]
    return missing


def connected_github(team_id: int, repository: str, installation_id: str | None) -> GitHubIntegration | None:
    owner = repository.split("/", 1)[0]
    github = docs_github(team_id, owner, priority=Priority.CRITICAL)
    if github is not None or not installation_id:
        return github
    try:
        GitHubIntegration.integration_from_installation_id(installation_id, team_id)
    except (*GITHUB_FAILURES, GitHubInstallationAccessFetchError):
        return None
    return docs_github(team_id, owner, priority=Priority.CRITICAL)


def task_run_link(team_id: int, task_id: UUID) -> str:
    return absolute_uri(f"/project/{team_id}/tasks/{task_id}")


def temporal_workflow_link(workflow_id: str) -> str:
    return (
        f"{settings.TEMPORAL_UI_HOST.rstrip('/')}/namespaces/{quote(settings.TEMPORAL_NAMESPACE, safe='')}"
        f"/workflows/{quote(workflow_id, safe='')}"
    )


def run_scratch_request(
    github: GitHubIntegration,
    writer: WriterSettings,
    team: Team,
    section: str,
    smoke_id: str,
    branches: list[str],
    announce: Callable[[str], object],
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
        "patches": {},
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
    return wait_for_pull_request(task_id, team.id, deadline, announce)


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
    announce: Callable[[str], object],
) -> WriterPullRequest:
    source = merged_source(github, source_url, writer.user_id)
    async_to_sync(initialize_self_capture_api_token)()
    deadline = time.monotonic() + timeout_minutes * 60
    try:
        outcome = intake.submit(smoke_verdict(section, source, smoke_id), team_id=team.id)
    except intake.WriterLaunchDeferred as error:
        raise CommandError("open writer pull requests could not be listed, retry") from error
    if outcome.status == "shadow":
        raise CommandError(
            f"Intake ran in shadow mode: turn the {AGENT_LAUNCH_FLAG} flag on at 100% for team {team.id}"
        )
    if outcome.task_id is None or outcome.status != "started":
        raise CommandError(f"Intake answered {outcome.status} for {source_url}")
    head_branch = tasks_facade.read_task_state_entry(outcome.task_id, team.id, HEAD_BRANCH_STATE_KEY)
    if isinstance(head_branch, str):
        branches.append(head_branch)
    return wait_for_pull_request(outcome.task_id, team.id, deadline, announce)


def wait_for_pull_request(
    task_id: UUID, team_id: int, deadline: float, announce: Callable[[str], object]
) -> WriterPullRequest:
    announce(f"task: {task_run_link(team_id, task_id)}")
    announced_run_ids: set[UUID] = set()
    failure: object = None
    while time.monotonic() < deadline:
        stored = tasks_facade.read_task_state_entry(task_id, team_id, PULL_REQUEST_STATE_KEY)
        if isinstance(stored, dict):
            opened = pull_request_json.validate_python(stored)
            announce(f"docs pull request: {opened.url}")
            return opened
        failure = tasks_facade.read_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY)
        if isinstance(failure, str):
            raise CommandError(f"Task {task_id} could not open its docs pull request: {failure}")
        for run_id in tasks_facade.list_task_run_ids(task_id, team_id):
            if run_id not in announced_run_ids:
                announced_run_ids.add(run_id)
                announce(f"publish workflow: {temporal_workflow_link(publish_workflow_id(run_id))}")
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
    except OpenPullRequestsUnavailable as error:
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
