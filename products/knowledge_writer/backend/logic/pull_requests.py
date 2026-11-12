import re
import time
from dataclasses import dataclass
from urllib.parse import quote
from uuid import UUID

import structlog

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
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
    HEAD_BRANCH_STATE_KEY,
    JOIN_STATE_KEY,
    PUBLICATION_CLAIM_STATE_KEY,
    PULL_REQUEST_FAILURE_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    REQUEST_STATE_KEY,
    SECTION_STATE_KEY,
    WriterPullRequest,
    is_publication_claim_live,
    publication_claim,
    publication_claim_owner,
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
COMPARE_FILE_LIMIT = 300


def reported_docs_branches(output: object, docs_repository: str) -> list[str]:
    return [
        head["branch"]
        for head in tasks_facade.read_head_branches(output)
        if head["repository"] == docs_repository.lower()
    ]


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


def refused_push_comment() -> str:
    return (
        "This branch did not pass the knowledge writer's checks after its latest run, so the run's source was not added. "
        "Review the new commits before you merge."
    )


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


REFUSAL_WARNING_ATTEMPTS = 3
REFUSAL_WARNING_BACKOFF_SECONDS = 2


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
        log_skipped_publication(task_run_id, team_id, "unconfigured")
        return None
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if run is None or run.task_origin_product != tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER:
        log_skipped_publication(task_run_id, team_id, "not_a_writer_run")
        return None
    reported_branches = reported_docs_branches(run.output, writer.docs_repository)
    if not reported_branches:
        log_skipped_publication(task_run_id, team_id, "no_docs_branch")
        return None
    published = tasks_facade.read_task_state_entry(run.task_id, team_id, PULL_REQUEST_STATE_KEY)
    if isinstance(published, dict):
        log_skipped_publication(task_run_id, team_id, "already_published")
        return pull_request_json.validate_python(published).url
    if not claim_publication(run.task_id, team_id, task_run_id):
        log_skipped_publication(task_run_id, team_id, "claim_held")
        return None
    try:
        return publish_claimed_pull_request(run.task_id, team_id, task_run_id, writer, reported_branches)
    except Exception:
        record_pull_request_failure(run.task_id, team_id, "github_request_failed")
        raise


def log_skipped_publication(task_run_id: UUID, team_id: int, reason: str) -> None:
    logger.info("knowledge_writer_publish_skipped", task_run_id=str(task_run_id), team_id=team_id, reason=reason)


def settle_publication(task_run_id: UUID, *, team_id: int, has_failed: bool) -> None:
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if run is None:
        return
    if has_failed:
        record_pull_request_failure(run.task_id, team_id, "publish_failed")
    release_publication_claim(run.task_id, team_id, task_run_id)


def claim_publication(task_id: UUID, team_id: int, task_run_id: UUID) -> bool:
    def claim(current: object) -> tuple[object, bool]:
        is_held_by_another_run = publication_claim_owner(current) != str(task_run_id)
        if is_held_by_another_run and is_publication_claim_live(current):
            return current, False
        return publication_claim(task_run_id), True

    return bool(tasks_facade.update_task_state_entry(task_id, team_id, PUBLICATION_CLAIM_STATE_KEY, claim))


def release_publication_claim(task_id: UUID, team_id: int, task_run_id: UUID) -> None:
    def release(current: object) -> tuple[object, None]:
        if publication_claim_owner(current) != str(task_run_id):
            return current, None
        return None, None

    tasks_facade.update_task_state_entry(task_id, team_id, PUBLICATION_CLAIM_STATE_KEY, release)


def publish_claimed_pull_request(
    task_id: UUID, team_id: int, task_run_id: UUID, writer: WriterSettings, reported_branches: list[str]
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
    issued = tasks_facade.read_task_state_entry(task_id, team_id, HEAD_BRANCH_STATE_KEY)
    head_branch = issued if isinstance(issued, str) and reported_branches == [issued] else None
    refusal = "head_branch_not_issued" if head_branch is None else publication_refusal(github, writer, head_branch)
    if head_branch is None or refusal is not None:
        refuse_publication(task_id, team_id, task_run_id, refusal or "head_branch_not_issued")
        if joined_pull_request is not None:
            warn_on_joined_pull_request(github, docs_name, joined_pull_request, team_id, task_run_id)
        return None
    pull_request = (
        add_source_to_pull_request(github, docs_name, joined_pull_request, request)
        if joined_pull_request is not None
        else open_pull_request(github, docs_name, request, head_branch, section=read_section(task_id, team_id))
    )
    if isinstance(pull_request, GitHubStepFailed):
        raise reported_step_failure(pull_request, team_id, task_run_id)
    stored = pull_request_json.dump_python(pull_request, mode="json")
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_STATE_KEY, replace_entry_with(stored))
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY, replace_entry_with(None))
    logger.info(
        "knowledge_writer_pull_request_published",
        task_id=str(task_id),
        task_run_id=str(task_run_id),
        team_id=team_id,
        pull_request_number=pull_request.number,
        section=pull_request.section,
        publication=publication_kind(joined_pull_request, pull_request),
    )
    return pull_request.url


def publication_kind(joined_pull_request: WriterPullRequest | None, published: WriterPullRequest) -> str:
    if joined_pull_request is None:
        return "opened"
    if joined_pull_request.number == published.number:
        return "joined"
    return "reopened_after_close"


def comparison_with_default_branch(github: GitHubIntegration, docs_repository: str, head_branch: str) -> dict:
    default_branch = github.get_default_branch(docs_repository)
    # GitHub lists a comparison's changed files on the first page only, capped at COMPARE_FILE_LIMIT.
    response = github.api_request(
        "GET",
        f"/repos/{docs_repository}/compare/{quote(default_branch, safe='/')}...{quote(head_branch, safe='/')}",
        endpoint="/repos/{owner}/{repo}/compare/{basehead}",
        params={"per_page": 1, "page": 1},
    )
    if response.status_code != 200:
        raise WriterPullRequestFailed(f"knowledge writer could not compare its docs branch: {response.status_code}")
    comparison = response.json()
    return comparison if isinstance(comparison, dict) else {}


def changed_paths(changed_files: list) -> list[str] | None:
    if not all(isinstance(changed_file, dict) for changed_file in changed_files):
        return None
    if not all(isinstance(changed_file.get("filename"), str) for changed_file in changed_files):
        return None
    return [
        path
        for changed_file in changed_files
        for path in (changed_file.get("filename"), changed_file.get("previous_filename"))
        if isinstance(path, str)
    ]


def publication_refusal(github: GitHubIntegration, writer: WriterSettings, head_branch: str) -> str | None:
    comparison = comparison_with_default_branch(github, writer.docs_repository, head_branch)
    changed_files = comparison.get("files")
    commits_ahead = comparison.get("ahead_by")
    if not isinstance(changed_files, list) or not isinstance(commits_ahead, int):
        return "comparison_unreadable"
    if commits_ahead == 0:
        return "no_changes"
    if len(changed_files) >= COMPARE_FILE_LIMIT:
        return "too_many_changed_files"
    paths = changed_paths(changed_files)
    if paths is None:
        return "comparison_unreadable"
    if any(not is_docs_path(path, writer.docs_paths) for path in paths):
        return "changed_paths_outside_docs"
    return None


def is_docs_path(path: str, docs_paths: tuple[str, ...]) -> bool:
    return any(path == docs_path or path.startswith(f"{docs_path}/") for docs_path in docs_paths)


def warn_on_joined_pull_request(
    github: GitHubIntegration, docs_name: str, pull_request: WriterPullRequest, team_id: int, task_run_id: UUID
) -> None:
    for attempt in range(REFUSAL_WARNING_ATTEMPTS):
        time.sleep(REFUSAL_WARNING_BACKOFF_SECONDS * attempt)
        try:
            commented = posted_refusal_warning(github, docs_name, pull_request.number)
        except Exception as error:
            logger.warning(
                "knowledge_writer_refusal_warning_failed",
                task_run_id=str(task_run_id),
                team_id=team_id,
                pull_request_number=pull_request.number,
                error_type=type(error).__name__,
            )
            capture_exception(error, {"team_id": team_id, "task_run_id": str(task_run_id)})
            return
        if commented.get("success"):
            return
        if not is_comment_failure_retryable(commented):
            break
    reported_step_failure(github_step_failed("comment_on_pull_request", commented), team_id, task_run_id)


def posted_refusal_warning(github: GitHubIntegration, docs_name: str, pull_request_number: int) -> dict:
    try:
        return github.comment_on_pull_request(docs_name, pull_request_number, refused_push_comment())
    except GitHubRateLimitError:
        return {"success": False, "status_code": 429}


def is_comment_failure_retryable(commented: dict) -> bool:
    status_code = commented.get("status_code")
    return isinstance(status_code, int) and (status_code == 429 or status_code >= 500)


def reported_step_failure(step_failed: GitHubStepFailed, team_id: int, task_run_id: UUID) -> WriterPullRequestFailed:
    logger.warning(
        "knowledge_writer_pull_request_step_failed",
        task_run_id=str(task_run_id),
        team_id=team_id,
        step=step_failed.step,
        status_code=step_failed.status_code,
    )
    failure = WriterPullRequestFailed("knowledge writer docs pull request failed")
    capture_exception(
        failure,
        {
            "team_id": team_id,
            "task_run_id": str(task_run_id),
            "step": step_failed.step,
            "status_code": step_failed.status_code,
        },
    )
    return failure


def refuse_publication(task_id: UUID, team_id: int, task_run_id: UUID, reason: str) -> None:
    capture_exception(
        WriterPullRequestFailed("knowledge writer refused to publish a docs branch"),
        {"team_id": team_id, "task_run_id": str(task_run_id), "reason": reason},
    )
    record_pull_request_failure(task_id, team_id, reason)


def record_pull_request_failure(task_id: UUID, team_id: int, reason: str) -> None:
    logger.warning("knowledge_writer_pull_request_failed", task_id=str(task_id), team_id=team_id, reason=reason)
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
        logger.warning(
            "knowledge_writer_section_label_failed",
            pull_request_number=pr_number,
            section=section,
            error_type=type(error).__name__,
        )
        capture_exception(error, {"pr_number": pr_number, "section": section})
        return
    if not labelled.get("success"):
        logger.warning(
            "knowledge_writer_section_label_failed",
            pull_request_number=pr_number,
            section=section,
            status_code=labelled.get("status_code"),
        )
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
