import re
from dataclasses import dataclass
from uuid import UUID

import structlog

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationManager
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import GitHubIntegration

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import DocsRequest
from ..settings import WriterSettings, writer_settings
from .launch import replace_entry_with
from .records import (
    JOIN_STATE_KEY,
    PUBLICATION_CLAIM_STATE_KEY,
    PULL_REQUEST_FAILURE_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    REQUEST_STATE_KEY,
    SECTION_STATE_KEY,
    WriterPullRequest,
    pull_request_json,
    request_json,
)
from .routing import SOURCE_REPOSITORY

logger = structlog.get_logger(__name__)

LINK_BACK_START = "<!-- knowledge-writer-sources -->"
LINK_BACK_END = "<!-- /knowledge-writer-sources -->"
SECTION_MARKER_PATTERN = re.compile(r"<!-- knowledge-writer-section: ([a-z0-9-]+) -->")
SECTION_LABEL_PREFIX = "knowledge-writer/"
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


def section_label(section: str) -> str:
    return f"{SECTION_LABEL_PREFIX}{section}"


def labelled_section(listed: dict) -> str | None:
    for label in listed.get("labels") or []:
        name = str((label or {}).get("name", ""))
        if name.startswith(SECTION_LABEL_PREFIX) and len(name) > len(SECTION_LABEL_PREFIX):
            return name.removeprefix(SECTION_LABEL_PREFIX)
    return None


def pull_request_body(request: DocsRequest, *, section: str | None) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    marker = f"\n{section_marker(section)}" if section else ""
    return f"The knowledge writer opened this{requester}.\n\n{link_back_block([request.source_url])}{marker}"


def joined_source_comment(request: DocsRequest) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    return f"The knowledge writer added a source to this pull request{requester}:\n\n- {request.source_url}"


def docs_github(team_id: int, docs_owner: str, *, priority: Priority) -> GitHubIntegration | None:
    for integration in IntegrationManager.github.oauth.list(team_id):
        if str(integration.config.get("account", {}).get("name", "")).lower() == docs_owner.lower():
            return GitHubIntegration(integration, source="knowledge_writer", priority=priority)
    return None


def source_repository_github(team_id: int) -> GitHubIntegration | None:
    return docs_github(team_id, SOURCE_REPOSITORY.split("/", 1)[0], priority=Priority.NORMAL)


def github_app_login() -> str | None:
    slug = get_instance_setting("GITHUB_APP_SLUG")
    return f"{slug}[bot]".lower() if slug else None


def writer_pull_request(listed: dict, docs_repository: str, app_login: str | None) -> WriterPullRequest | None:
    body = listed.get("body") or ""
    head = listed.get("head") or {}
    head_repository = str((head.get("repo") or {}).get("full_name", "")).lower()
    author_login = str((listed.get("user") or {}).get("login", "")).lower()
    if app_login is None or author_login != app_login:
        return None
    if head_repository != docs_repository.lower():
        return None
    label_section = labelled_section(listed)
    if label_section is None and LINK_BACK_START not in body:
        return None
    marker_section = SECTION_MARKER_PATTERN.search(body)
    return WriterPullRequest(
        number=listed["number"],
        url=listed["html_url"],
        head_branch=head["ref"],
        section=label_section or (marker_section.group(1) if marker_section else None),
    )


def open_writer_pull_requests(writer: WriterSettings) -> list[WriterPullRequest] | None:
    github = docs_github(writer.team_id, writer.docs_repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        return None
    app_login = github_app_login()
    found: list[WriterPullRequest] = []
    for page in range(1, MAX_PULL_REQUEST_PAGES + 1):
        try:
            response = github.api_request(
                "GET",
                f"/repos/{writer.docs_repository}/pulls",
                endpoint="/repos/{owner}/{repo}/pulls",
                params={"state": "open", "per_page": PULL_REQUESTS_PER_PAGE, "page": page},
            )
        except GitHubEgressBudgetExhausted:
            logger.warning("knowledge_writer_open_pull_requests_deferred")
            return None
        if response.status_code != 200:
            logger.warning("knowledge_writer_open_pull_requests_failed", status_code=response.status_code)
            return None
        listed_page = response.json()
        found.extend(
            pull_request
            for pull_request in (
                writer_pull_request(listed, writer.docs_repository, app_login) for listed in listed_page
            )
            if pull_request is not None
        )
        if len(listed_page) < PULL_REQUESTS_PER_PAGE:
            return found
    logger.warning("knowledge_writer_open_pull_requests_truncated", pages=MAX_PULL_REQUEST_PAGES)
    return None


class WriterPullRequestFailed(Exception):
    pass


@dataclass(frozen=True)
class GitHubStepFailed:
    step: str
    status_code: int | None


def github_step_failed(step: str, response: dict) -> GitHubStepFailed:
    status_code = response.get("status_code")
    return GitHubStepFailed(step=step, status_code=status_code if isinstance(status_code, int) else None)


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
    if not claim_publication(run.task_id, team_id, task_run_id):
        return None
    try:
        pull_request_url = publish_claimed_pull_request(run.task_id, team_id, task_run_id, writer, head_branch)
    except Exception:
        record_pull_request_failure(run.task_id, team_id, "github_request_failed")
        release_publication_claim(run.task_id, team_id, task_run_id)
        raise
    if pull_request_url is None:
        release_publication_claim(run.task_id, team_id, task_run_id)
    return pull_request_url


def claim_publication(task_id: UUID, team_id: int, task_run_id: UUID) -> bool:
    def claim(current: object) -> tuple[object, bool]:
        if current is not None:
            return current, False
        return str(task_run_id), True

    return bool(tasks_facade.update_task_state_entry(task_id, team_id, PUBLICATION_CLAIM_STATE_KEY, claim))


def release_publication_claim(task_id: UUID, team_id: int, task_run_id: UUID) -> None:
    def release(current: object) -> tuple[object, None]:
        if current != str(task_run_id):
            return current, None
        return None, None

    tasks_facade.update_task_state_entry(task_id, team_id, PUBLICATION_CLAIM_STATE_KEY, release)


def publish_claimed_pull_request(
    task_id: UUID, team_id: int, task_run_id: UUID, writer: WriterSettings, head_branch: str
) -> str | None:
    request = request_json.validate_python(tasks_facade.read_task_state_entry(task_id, team_id, REQUEST_STATE_KEY))
    docs_owner, docs_name = writer.docs_repository.split("/", 1)
    github = docs_github(team_id, docs_owner, priority=Priority.CRITICAL)
    if github is None:
        logger.warning("knowledge_writer_no_docs_github_integration", team_id=team_id, task_run_id=str(task_run_id))
        record_pull_request_failure(task_id, team_id, "no_github_integration")
        return None
    joined = tasks_facade.read_task_state_entry(task_id, team_id, JOIN_STATE_KEY)
    joined_pull_request = pull_request_json.validate_python(joined) if isinstance(joined, dict) else None
    if joined_pull_request is not None and joined_pull_request.head_branch != head_branch:
        capture_exception(
            WriterPullRequestFailed("knowledge writer pushed to a branch other than the joined pull request's"),
            {"team_id": team_id, "task_run_id": str(task_run_id)},
        )
        record_pull_request_failure(task_id, team_id, "joined_branch_mismatch")
        return None
    pull_request = (
        add_source_to_pull_request(github, docs_name, joined_pull_request, request)
        if joined_pull_request is not None
        else open_pull_request(github, docs_name, request, head_branch, section=read_section(task_id, team_id))
    )
    if isinstance(pull_request, GitHubStepFailed):
        capture_exception(
            WriterPullRequestFailed("knowledge writer docs pull request failed"),
            {
                "team_id": team_id,
                "task_run_id": str(task_run_id),
                "step": pull_request.step,
                "status_code": pull_request.status_code,
            },
        )
        record_pull_request_failure(task_id, team_id, "github_request_failed")
        return None
    stored = pull_request_json.dump_python(pull_request, mode="json")
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_STATE_KEY, replace_entry_with(stored))
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY, replace_entry_with(None))
    return pull_request.url


def record_pull_request_failure(task_id: UUID, team_id: int, reason: str) -> None:
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY, replace_entry_with(reason))


def read_section(task_id: UUID, team_id: int) -> str | None:
    section = tasks_facade.read_task_state_entry(task_id, team_id, SECTION_STATE_KEY)
    return section if isinstance(section, str) else None


def open_pull_request(
    github: GitHubIntegration, docs_name: str, request: DocsRequest, head_branch: str, *, section: str | None
) -> WriterPullRequest | GitHubStepFailed:
    created = github.create_pull_request(
        docs_name,
        title=f"docs: update for {request.source_url}"[:255],
        body=pull_request_body(request, section=section),
        head_branch=head_branch,
        draft=True,
    )
    if not created.get("success"):
        return github_step_failed("create_pull_request", created)
    if section:
        label_pull_request_section(github, docs_name, created["pr_number"], section)
    return WriterPullRequest(
        number=created["pr_number"], url=created["pr_url"], head_branch=head_branch, section=section
    )


def label_pull_request_section(github: GitHubIntegration, docs_name: str, pr_number: int, section: str) -> None:
    try:
        labelled = github.add_pull_request_labels(docs_name, pr_number, [section_label(section)])
    except Exception as error:
        capture_exception(error, {"pr_number": pr_number, "section": section})
        return
    if not labelled.get("success"):
        capture_exception(
            WriterPullRequestFailed("knowledge writer could not label its docs pull request"),
            {"pr_number": pr_number, "section": section, "status_code": labelled.get("status_code")},
        )


def add_source_to_pull_request(
    github: GitHubIntegration, docs_name: str, pull_request: WriterPullRequest, request: DocsRequest
) -> WriterPullRequest | GitHubStepFailed:
    current = github.get_pull_request(docs_name, pull_request.number)
    if not current.get("success"):
        return github_step_failed("get_pull_request", current)
    if current.get("state") != "open":
        return open_pull_request(github, docs_name, request, pull_request.head_branch, section=pull_request.section)
    commented = github.comment_on_pull_request(docs_name, pull_request.number, joined_source_comment(request))
    if not commented.get("success"):
        return github_step_failed("comment_on_pull_request", commented)
    return pull_request
