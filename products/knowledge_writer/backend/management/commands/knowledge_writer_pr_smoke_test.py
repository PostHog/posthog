import time
import base64
import secrets
import dataclasses
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from asgiref.sync import async_to_sync

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.models.team import Team
from posthog.utils import initialize_self_capture_api_token

from products.tasks.backend.facade import api as tasks_facade

from ...adapters import REGISTRY
from ...facade.contracts import AdapterVerdict, DocsCommandRequest, DocsRequest
from ...facade.enums import DocsRequestSource
from ...feature_flags import AGENT_LAUNCH_FLAG
from ...logic import intake
from ...logic.intake import pull_request_to_join
from ...logic.launch import start_writer
from ...logic.pull_requests import LINK_BACK_START, docs_github, open_writer_pull_requests, section_marker
from ...logic.records import PULL_REQUEST_STATE_KEY, WriterPullRequest, pull_request_json
from ...logic.routing import route_request
from ...settings import WriterSettings, writer_settings

PRODUCTION_DOCS_REPOSITORY = "posthog/posthog.com"
SCRATCH_PAGE_NAME = "knowledge-writer-smoke-test.mdx"
UNREACHABLE_PULL_REQUEST_FLOOR = 900_000_000
GITHUB_FAILURES = (GitHubIntegrationError, GitHubRateLimitError)
AGENT_POLL_INTERVAL_SECONDS = 15
SMOKE_NOTE = "Knowledge writer smoke test."
SMOKE_REQUESTER = "knowledge-writer-smoke-test"
SmokeRequests = tuple[WriterPullRequest, bool, WriterPullRequest, bool]


class Command(BaseCommand):
    help = "Open and join a draft docs pull request on a scratch docs repository, check it, and clean up."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--repo", required=True, help="Scratch docs repository as owner/name, never PostHog/posthog.com"
        )
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument(
            "--installation-id", help="GitHub App installation to connect when the team has none for the repo owner"
        )
        parser.add_argument("--section", default="session-replay", help="Docs section both requests target")
        parser.add_argument(
            "--with-agent",
            nargs=2,
            metavar="SOURCE_PULL_REQUEST_URL",
            help="Run the real writer agent for two merged pull requests whose change the section's docs lack",
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
        github = connected_github(team.id, repository, options["installation_id"])
        section: str = options["section"]
        stale = pull_request_to_join(list_writer_pull_requests(writer), section)
        if stale is not None:
            raise CommandError(f"Close the open writer pull request for {section} first: {stale.url}")

        smoke_id = secrets.token_hex(4)
        source_urls: list[str] | None = options["with_agent"]
        branches: list[str] = []
        try:
            opened, first_joined, joined, second_joined = (
                run_agent_requests(
                    github, team, section, source_urls, smoke_id, options["agent_timeout_minutes"], branches
                )
                if source_urls
                else run_scratch_requests(github, writer, team, section, smoke_id, branches)
            )
            failures = check_pull_request(github, repository, section, opened, first_joined, joined, second_joined)
        finally:
            cleanup_problems = clean_up(github, writer, repository, branches)
            for problem in cleanup_problems:
                self.stderr.write(f"CLEANUP FAILED {problem}")
        failures += cleanup_problems
        for failure in failures:
            self.stderr.write(f"FAIL {failure}")
        if failures:
            raise CommandError(f"{len(failures)} check(s) failed on {opened.url}")
        self.stdout.write(f"PASS draft pull request {opened.url} opened, joined by comment, closed and cleaned up")


def connected_github(team_id: int, repository: str, installation_id: str | None) -> GitHubIntegration:
    owner = repository.split("/", 1)[0]
    github = docs_github(team_id, owner)
    if github is None and installation_id:
        GitHubIntegration.integration_from_installation_id(installation_id, team_id)
        github = docs_github(team_id, owner)
    if github is None:
        raise CommandError(f"Team {team_id} has no GitHub integration for {owner}; pass --installation-id")
    return github


def list_writer_pull_requests(writer: WriterSettings) -> list[WriterPullRequest]:
    open_pull_requests = open_writer_pull_requests(writer)
    if open_pull_requests is None:
        raise CommandError(f"Could not list open pull requests on {writer.docs_repository}")
    return open_pull_requests


def push_scratch_branch(github: GitHubIntegration, repository: str, branch: str, section: str) -> None:
    default_branch = github.get_default_branch(repository)
    base = github.api_request(
        "GET", f"/repos/{repository}/git/ref/heads/{default_branch}", endpoint="/repos/{owner}/{repo}/git/ref/{ref}"
    )
    if base.status_code != 200:
        raise CommandError(f"Could not read {default_branch} on {repository}: {base.text}")
    created = github.api_request(
        "POST",
        f"/repos/{repository}/git/refs",
        endpoint="/repos/{owner}/{repo}/git/refs",
        json_body={"ref": f"refs/heads/{branch}", "sha": base.json()["object"]["sha"]},
    )
    if created.status_code != 201:
        raise CommandError(f"Could not create {branch}: {created.text}")
    committed = github.api_request(
        "PUT",
        f"/repos/{repository}/contents/contents/docs/{section}/{SCRATCH_PAGE_NAME}",
        endpoint="/repos/{owner}/{repo}/contents/{path}",
        json_body={
            "message": "docs: knowledge writer smoke test",
            "content": base64.b64encode(f"Knowledge writer smoke test on {branch}.\n".encode()).decode(),
            "branch": branch,
        },
    )
    if committed.status_code != 201:
        raise CommandError(f"Could not commit to {branch}: {committed.text}")


def run_scratch_requests(
    github: GitHubIntegration, writer: WriterSettings, team: Team, section: str, smoke_id: str, branches: list[str]
) -> SmokeRequests:
    for number in (1, 2):
        branch = f"knowledge-writer-smoke-{smoke_id}-{number}"
        branches.append(branch)
        push_scratch_branch(github, writer.docs_repository, branch, section)
    opened, first_joined = run_writer_request(writer, team, section, branches[0])
    joined, second_joined = run_writer_request(writer, team, section, branches[1])
    return opened, first_joined, joined, second_joined


def run_agent_requests(
    github: GitHubIntegration,
    team: Team,
    section: str,
    source_urls: list[str],
    smoke_id: str,
    timeout_minutes: int,
    branches: list[str],
) -> SmokeRequests:
    first_source, second_source = (merged_source(github, url) for url in source_urls)
    async_to_sync(initialize_self_capture_api_token)()
    deadline = time.monotonic() + timeout_minutes * 60
    opened, first_joined = run_agent_request(team, section, first_source, f"{smoke_id}-1", deadline)
    branches.append(opened.head_branch)
    joined, second_joined = run_agent_request(team, section, second_source, f"{smoke_id}-2", deadline)
    return opened, first_joined, joined, second_joined


def merged_source(github: GitHubIntegration, source_url: str) -> DocsCommandRequest:
    pull_request = github.get_pull_request_from_url(source_url)
    if not pull_request.get("success"):
        raise CommandError(f"Could not read {source_url}: {pull_request.get('error')}")
    # The agent refuses to push for a source it cannot verify, so an unmerged one burns a full run.
    if not pull_request.get("merged"):
        raise CommandError(f"{source_url} is not merged")
    return DocsCommandRequest(
        repository=pull_request["repository"],
        pull_request_number=pull_request["number"],
        pull_request_url=pull_request["url"],
        head_sha=pull_request["head_sha"],
        note=SMOKE_NOTE,
        requested_by=SMOKE_REQUESTER,
    )


def unreachable_source() -> DocsCommandRequest:
    source_number = UNREACHABLE_PULL_REQUEST_FLOOR + secrets.randbelow(UNREACHABLE_PULL_REQUEST_FLOOR)
    return DocsCommandRequest(
        repository="PostHog/posthog",
        pull_request_number=source_number,
        pull_request_url=f"https://github.com/PostHog/posthog/pull/{source_number}",
        head_sha=secrets.token_hex(20),
        note=SMOKE_NOTE,
        requested_by=SMOKE_REQUESTER,
    )


def smoke_verdict(section: str, source: DocsCommandRequest, smoke_suffix: str) -> AdapterVerdict:
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(source)
    return dataclasses.replace(verdict, request=smoke_request(verdict, section, smoke_suffix))


def smoke_request(verdict: AdapterVerdict, section: str, smoke_suffix: str) -> DocsRequest:
    if verdict.request is None:
        raise CommandError(f"The command adapter asked for no docs: {verdict.reason}")
    return dataclasses.replace(
        verdict.request,
        suggested_page_urls=(f"https://posthog.com/docs/{section}",),
        dedupe_id=f"knowledge_writer:command_tag:smoke-{smoke_suffix}",
    )


def run_agent_request(
    team: Team, section: str, source: DocsCommandRequest, smoke_suffix: str, deadline: float
) -> tuple[WriterPullRequest, bool]:
    outcome = intake.submit(smoke_verdict(section, source, smoke_suffix), team_id=team.id)
    if outcome.status == "shadow":
        raise CommandError(
            f"Intake ran in shadow mode: turn the {AGENT_LAUNCH_FLAG} flag on at 100% for team {team.id}"
        )
    if outcome.task_id is None or outcome.status not in ("started", "joined"):
        raise CommandError(f"Intake answered {outcome.status} for {source.pull_request_url}")
    return wait_for_pull_request(outcome.task_id, team.id, deadline), outcome.status == "joined"


def wait_for_pull_request(task_id: UUID, team_id: int, deadline: float) -> WriterPullRequest:
    while time.monotonic() < deadline:
        ended_runs = [
            run
            for run_id in tasks_facade.list_task_run_ids(task_id, team_id)
            if (run := tasks_facade.get_task_run(run_id, team_id)) is not None and run.is_terminal
        ]
        stored = tasks_facade.read_task_state_entry(task_id, team_id, PULL_REQUEST_STATE_KEY)
        if isinstance(stored, dict):
            return pull_request_json.validate_python(stored)
        if ended_runs:
            run = ended_runs[0]
            raise CommandError(
                f"Writer run {run.id} on task {task_id} ended {run.status} without a pull request: {run.error_message}"
            )
        time.sleep(AGENT_POLL_INTERVAL_SECONDS)
    raise CommandError(f"Timed out waiting for task {task_id} to record a pull request")


def run_writer_request(writer: WriterSettings, team: Team, section: str, branch: str) -> tuple[WriterPullRequest, bool]:
    request = smoke_request(REGISTRY[DocsRequestSource.COMMAND_TAG].assess(unreachable_source()), section, branch)
    routing = route_request(request, team_id=team.id)
    joining = pull_request_to_join(list_writer_pull_requests(writer), routing.section)
    task_id = start_writer(request, routing, team=team, writer=writer, joining=joining, start_workflow=False)
    for run_id in tasks_facade.list_task_run_ids(task_id, team.id):
        tasks_facade.update_task_run(
            run_id,
            task_id,
            team.id,
            validated_data={
                "status": "completed",
                "output": {"head_branches": [{"repository": writer.docs_repository, "branch": branch}]},
            },
        )
    stored = tasks_facade.read_task_state_entry(task_id, team.id, PULL_REQUEST_STATE_KEY)
    if not isinstance(stored, dict):
        raise CommandError(f"The finished run on {branch} recorded no pull request")
    return pull_request_json.validate_python(stored), joining is not None


def check_pull_request(
    github: GitHubIntegration,
    repository: str,
    section: str,
    opened: WriterPullRequest,
    first_joined: bool,
    joined: WriterPullRequest,
    second_joined: bool,
) -> list[str]:
    pull_request = github.api_request(
        "GET", f"/repos/{repository}/pulls/{opened.number}", endpoint="/repos/{owner}/{repo}/pulls/{pull_number}"
    ).json()
    comments = github.api_request(
        "GET",
        f"/repos/{repository}/issues/{opened.number}/comments",
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}/comments",
    ).json()
    body = pull_request.get("body") or ""
    checks = {
        "the first request opened a pull request instead of joining one": not first_joined,
        "the second request joined the first pull request": second_joined and joined.number == opened.number,
        "the pull request is a draft": pull_request.get("draft") is True,
        "the body has the link-back block": LINK_BACK_START in body,
        "the body has the section marker": section_marker(section) in body,
        "there is exactly one source comment": len(comments) == 1,
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
