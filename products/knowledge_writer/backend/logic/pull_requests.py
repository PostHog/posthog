import re
from uuid import UUID

import structlog

from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import GitHubIntegration, Integration

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import DocsRequest
from ..settings import WriterSettings, writer_settings
from .records import (
    JOIN_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    REQUEST_STATE_KEY,
    SECTION_STATE_KEY,
    WriterPullRequest,
    pull_request_json,
    request_json,
)

logger = structlog.get_logger(__name__)

LINK_BACK_START = "<!-- knowledge-writer-sources -->"
LINK_BACK_END = "<!-- /knowledge-writer-sources -->"
SECTION_MARKER_PATTERN = re.compile(r"<!-- knowledge-writer-section: ([a-z0-9-]+) -->")
PULL_REQUESTS_PER_PAGE = 100
MAX_PULL_REQUEST_PAGES = 20


def docs_head_branch(output: object, docs_repository: str) -> str | None:
    for head in tasks_facade.read_head_branches(output):
        if head["repository"] == docs_repository.lower():
            return head["branch"]
    return None


def link_back_block(source_urls: list[str]) -> str:
    lines = [f"- {source_url}" for source_url in source_urls]
    return "\n".join([LINK_BACK_START, *lines, LINK_BACK_END])


def section_marker(section: str) -> str:
    return f"<!-- knowledge-writer-section: {section} -->"


def pull_request_body(request: DocsRequest, *, section: str | None) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    marker = f"\n{section_marker(section)}" if section else ""
    return f"The knowledge writer opened this{requester}.\n\n{link_back_block([request.source_url])}{marker}"


def joined_source_comment(request: DocsRequest) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    return f"The knowledge writer added a source to this pull request{requester}:\n\n- {request.source_url}"


def docs_github(team_id: int, docs_owner: str) -> GitHubIntegration | None:
    for integration in Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
        if str(integration.config.get("account", {}).get("name", "")).lower() == docs_owner.lower():
            return GitHubIntegration(integration, source="knowledge_writer", priority=Priority.CRITICAL)
    return None


def writer_pull_request(listed: dict, docs_repository: str) -> WriterPullRequest | None:
    body = listed.get("body") or ""
    head = listed.get("head") or {}
    head_repository = str((head.get("repo") or {}).get("full_name", "")).lower()
    if LINK_BACK_START not in body or head_repository != docs_repository.lower():
        return None
    section = SECTION_MARKER_PATTERN.search(body)
    return WriterPullRequest(
        number=listed["number"],
        url=listed["html_url"],
        head_branch=head["ref"],
        section=section.group(1) if section else None,
    )


def open_writer_pull_requests(writer: WriterSettings) -> list[WriterPullRequest] | None:
    github = docs_github(writer.team_id, writer.docs_repository.split("/", 1)[0])
    if github is None:
        return None
    found: list[WriterPullRequest] = []
    for page in range(1, MAX_PULL_REQUEST_PAGES + 1):
        response = github.api_request(
            "GET",
            f"/repos/{writer.docs_repository}/pulls",
            endpoint="/repos/{owner}/{repo}/pulls",
            params={"state": "open", "per_page": PULL_REQUESTS_PER_PAGE, "page": page},
        )
        if response.status_code != 200:
            logger.warning("knowledge_writer_open_pull_requests_failed", status_code=response.status_code)
            return None
        listed_page = response.json()
        found.extend(
            pull_request
            for pull_request in (writer_pull_request(listed, writer.docs_repository) for listed in listed_page)
            if pull_request is not None
        )
        if len(listed_page) < PULL_REQUESTS_PER_PAGE:
            return found
    logger.warning("knowledge_writer_open_pull_requests_truncated", pages=MAX_PULL_REQUEST_PAGES)
    return None


class WriterPullRequestFailed(Exception):
    pass


def open_or_join_pull_request(task_run_id: UUID, *, team_id: int) -> str | None:
    writer = writer_settings()
    if writer is None or writer.team_id != team_id:
        return None
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if run is None or run.task_origin_product != tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER:
        return None
    head_branch = docs_head_branch(run.output, writer.docs_repository)
    if head_branch is None:
        return None
    published = tasks_facade.read_task_state_entry(run.task_id, team_id, PULL_REQUEST_STATE_KEY)
    if isinstance(published, dict):
        return pull_request_json.validate_python(published).url
    request = request_json.validate_python(tasks_facade.read_task_state_entry(run.task_id, team_id, REQUEST_STATE_KEY))
    docs_owner, docs_name = writer.docs_repository.split("/", 1)
    github = docs_github(team_id, docs_owner)
    if github is None:
        logger.warning("knowledge_writer_no_docs_github_integration", team_id=team_id, task_run_id=str(task_run_id))
        return None
    joined = tasks_facade.read_task_state_entry(run.task_id, team_id, JOIN_STATE_KEY)
    pull_request = (
        add_source_to_pull_request(github, docs_name, pull_request_json.validate_python(joined), request)
        if isinstance(joined, dict)
        else open_pull_request(github, docs_name, request, head_branch, section=read_section(run.task_id, team_id))
    )
    if pull_request is None:
        capture_exception(
            WriterPullRequestFailed("knowledge writer docs pull request failed"),
            {"team_id": team_id, "task_run_id": str(task_run_id)},
        )
        return None
    stored = pull_request_json.dump_python(pull_request, mode="json")
    tasks_facade.update_task_state_entry(run.task_id, team_id, PULL_REQUEST_STATE_KEY, lambda _current: (stored, None))
    return pull_request.url


def read_section(task_id: UUID, team_id: int) -> str | None:
    section = tasks_facade.read_task_state_entry(task_id, team_id, SECTION_STATE_KEY)
    return section if isinstance(section, str) else None


def open_pull_request(
    github: GitHubIntegration, docs_name: str, request: DocsRequest, head_branch: str, *, section: str | None
) -> WriterPullRequest | None:
    created = github.create_pull_request(
        docs_name,
        title=f"docs: update for {request.source_url}"[:255],
        body=pull_request_body(request, section=section),
        head_branch=head_branch,
    )
    if not created.get("success"):
        return None
    return WriterPullRequest(
        number=created["pr_number"], url=created["pr_url"], head_branch=head_branch, section=section
    )


def add_source_to_pull_request(
    github: GitHubIntegration, docs_name: str, pull_request: WriterPullRequest, request: DocsRequest
) -> WriterPullRequest | None:
    current = github.get_pull_request(docs_name, pull_request.number)
    if not current.get("success"):
        return None
    if current.get("state") != "open":
        return open_pull_request(github, docs_name, request, pull_request.head_branch, section=pull_request.section)
    commented = github.comment_on_pull_request(docs_name, pull_request.number, joined_source_comment(request))
    if not commented.get("success"):
        return None
    return pull_request
