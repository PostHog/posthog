import base64
import secrets
import dataclasses

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.models.team import Team

from products.tasks.backend.facade import api as tasks_facade

from ...adapters import REGISTRY
from ...facade.contracts import DocsCommandRequest, DocsRequest
from ...facade.enums import DocsRequestSource
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
        branches = [f"knowledge-writer-smoke-{smoke_id}-{number}" for number in (1, 2)]
        try:
            for branch in branches:
                push_scratch_branch(github, repository, branch, section)
            opened, first_joined = run_writer_request(writer, team, section, branches[0])
            joined, second_joined = run_writer_request(writer, team, section, branches[1])
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


def smoke_request(section: str) -> DocsRequest:
    source_number = UNREACHABLE_PULL_REQUEST_FLOOR + secrets.randbelow(UNREACHABLE_PULL_REQUEST_FLOOR)
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(
        DocsCommandRequest(
            repository="PostHog/posthog",
            pull_request_number=source_number,
            pull_request_url=f"https://github.com/PostHog/posthog/pull/{source_number}",
            head_sha=secrets.token_hex(20),
            note="Knowledge writer smoke test.",
            requested_by="knowledge-writer-smoke-test",
        )
    )
    if verdict.request is None:
        raise CommandError(f"The command adapter asked for no docs: {verdict.reason}")
    return dataclasses.replace(verdict.request, suggested_page_urls=(f"https://posthog.com/docs/{section}",))


def run_writer_request(writer: WriterSettings, team: Team, section: str, branch: str) -> tuple[WriterPullRequest, bool]:
    request = smoke_request(section)
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
