import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal
from urllib.parse import quote, urlparse
from uuid import UUID

import requests
import structlog

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationManager
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import GitHubIntegration, GitHubIntegrationError
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ..facade.contracts import DocsRequest
from ..feature_flags import open_pull_requests_flag_state
from ..settings import WriterSettings, docs_source_for, writer_settings
from .docs_pages import (
    DOCS_SOURCE_EXTENSIONS,
    CompanionCheck,
    PatchMismatch,
    ancestor_directories,
    changed_file_entry,
    changed_file_status,
    companion_check,
    decoded_text,
    extra_pages,
    is_companion_path,
    is_editable_base_mode,
)
from .grounding import MAX_GROUNDED_LINES, GroundingResult, ground_draft
from .launch import HEAD_BRANCH_PREFIX, replace_entry_with
from .records import (
    BASE_SHA_STATE_KEY,
    DOCS_CONTENT_ROOT_STATE_KEY,
    HEAD_BRANCH_STATE_KEY,
    PULL_REQUEST_FAILURE_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    REQUEST_STATE_KEY,
    ROUTED_PAGE_KEYS_STATE_KEY,
    SOURCE_CHANGE_STATE_KEY,
    SourceChange,
    WriterPullRequest,
    pull_request_json,
    stored_request,
    stored_source_change,
)
from .routing import SOURCE_REPOSITORY
from .server_commit import (
    DIRECTORY_MODE,
    BaseEntry,
    BaseTree,
    CommitIdentity,
    DocsCommitFailed,
    base_tree,
    build_commit,
    publish_ref,
)
from .writer_change import (
    WriterChange,
    WriterChangeRefused,
    docs_folders_of,
    parse_writer_change,
    writer_change_artifact,
)

logger = structlog.get_logger(__name__)

GITHUB_READ_ERRORS = (
    requests.RequestException,
    GitHubIntegrationError,
    GitHubRateLimitError,
    GitHubEgressBudgetExhausted,
)

LINK_BACK_START = "<!-- knowledge-writer-sources -->"
LINK_BACK_END = "<!-- /knowledge-writer-sources -->"
PULL_REQUESTS_PER_PAGE = 100
MAX_PULL_REQUEST_PAGES = 20
DRAFT_EVENT = "knowledge_writer draft"
OUTCOME_EVENT = "knowledge_writer outcome"
REVIEWS_PER_PAGE = 100
MAX_REVIEW_PAGES = 10
SECONDS_PER_HOUR = 3600
DRAFT_FILE_PATCH_CHARACTERS = 4_000
DRAFT_PATCH_BUDGET_CHARACTERS = 60_000
MAX_DRAFTED_FILES = 200
OPEN_PULL_REQUESTS_OFF = "open_pull_requests_off"
NO_HUMAN_AUTHOR = "no_human_author"
REVIEW_REQUEST_FAILED = "review_request_failed"
REVIEW_REQUEST_REJECTED = "review_request_rejected"
MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
DraftOutcome = Literal["refused", "logged", "opened", "failed"]
CloseReason = Literal["merged", "closed_by_reviewer", "closed_stale"]
MAX_LISTED_UNSUPPORTED_LINES = 50
MAX_LISTED_LINE_CHARACTERS = 300
MAX_LISTED_COMPANION_FLAGS = 50


def link_back_block(source_urls: list[str]) -> str:
    lines = [f"- {source_url}" for source_url in source_urls]
    return "\n".join([LINK_BACK_START, *lines, LINK_BACK_END])


@dataclass(frozen=True)
class DraftFlags:
    grounding: GroundingResult
    extra_pages: tuple[str, ...]
    companion_flags: tuple[str, ...]
    rules_flags: tuple[str, ...] = ()
    unrun_enforcers: tuple[str, ...] = ()

    @property
    def is_ready_for_review(self) -> bool:
        return (
            self.grounding.ran
            and not self.grounding.unsupported_lines
            and not self.extra_pages
            and not self.companion_flags
            and not self.rules_flags
            and not self.unrun_enforcers
        )


def pull_request_body(request: DocsRequest, flags: DraftFlags) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    return "\n\n".join(
        [f"The knowledge writer opened this{requester}.", *flag_sections(flags), link_back_block([request.source_url])]
    )


def listed_companion_flags(flags: DraftFlags) -> tuple[str, ...]:
    return (*flags.rules_flags, *flags.companion_flags[:MAX_LISTED_COMPANION_FLAGS])


def flag_sections(flags: DraftFlags) -> list[str]:
    if flags.is_ready_for_review:
        return []
    sections = ["This is a draft. Check what is listed below before you mark it ready for review."]
    if not flags.grounding.ran:
        sections.append("Grounding did not run, so no added line was checked against the source change.")
    unsupported_lines = flags.grounding.unsupported_lines
    if unsupported_lines:
        listed_lines = tuple(listed_line(line) for line in unsupported_lines[:MAX_LISTED_UNSUPPORTED_LINES])
        unlisted_count = len(unsupported_lines) - len(listed_lines)
        sections.append("These added lines have no supporting quote in the source change:")
        sections.append(fenced_block(listed_lines))
        if unlisted_count:
            sections.append(f"{unlisted_count} more unsupported lines are not listed.")
    if flags.extra_pages:
        sections.append("These existing pages changed but were not routed to this request:")
        sections.append("\n".join(f"- {page_path}" for page_path in flags.extra_pages))
    if flags.rules_flags or flags.companion_flags:
        listed_flags = tuple(listed_line(flag) for flag in listed_companion_flags(flags))
        unlisted_count = len(flags.rules_flags) + len(flags.companion_flags) - len(listed_flags)
        sections.append("Check these edits outside the docs pages:")
        sections.append(fenced_block(listed_flags))
        if unlisted_count:
            sections.append(f"{unlisted_count} more edits outside the docs pages are not listed.")
    if flags.unrun_enforcers:
        sections.append(
            "The repository's own checks could not run in the writer's sandbox. "
            "Run them on the changed files before you merge:"
        )
        sections.append(fenced_block(tuple(listed_line(enforcer) for enforcer in flags.unrun_enforcers)))
    return sections


def listed_line(line: str) -> str:
    if len(line) <= MAX_LISTED_LINE_CHARACTERS:
        return line
    return f"{line[:MAX_LISTED_LINE_CHARACTERS]}..."


def fenced_block(lines: tuple[str, ...]) -> str:
    longest_backtick_run = max((len(run) for line in lines for run in re.findall(r"`+", line)), default=0)
    fence = "`" * max(3, longest_backtick_run + 1)
    return "\n".join([f"{fence}text", *lines, fence])


def docs_github(team_id: int, docs_owner: str, *, priority: Priority) -> GitHubIntegration | None:
    for integration in IntegrationManager.github.oauth.list(team_id):
        if str(integration.config.get("account", {}).get("name", "")).lower() == docs_owner.lower():
            return GitHubIntegration(integration, source="knowledge_writer", priority=priority)
    return None


def source_repository_github(team_id: int) -> GitHubIntegration | None:
    return docs_github(team_id, SOURCE_REPOSITORY.split("/", 1)[0], priority=Priority.NORMAL)


def source_github(team_id: int, source: SourceChange) -> GitHubIntegration | None:
    if source.repository is None:
        return None
    return docs_github(team_id, source.repository.split("/", 1)[0], priority=Priority.NORMAL)


def github_app_login() -> str | None:
    slug = get_instance_setting("GITHUB_APP_SLUG")
    return f"{slug}[bot]".lower() if slug else None


def writer_commit_identity() -> CommitIdentity | None:
    slug = get_instance_setting("GITHUB_APP_SLUG")
    if not slug:
        return None
    return CommitIdentity(name=f"{slug}[bot]", email=f"{slug}[bot]@users.noreply.github.com")


def writer_pull_request(listed: dict, docs_repository: str, app_login: str | None) -> WriterPullRequest | None:
    body = listed.get("body") or ""
    head = listed.get("head") or {}
    head_repository = str((head.get("repo") or {}).get("full_name", "")).lower()
    author_login = str((listed.get("user") or {}).get("login", "")).lower()
    if app_login is None or author_login != app_login:
        return None
    if head_repository != docs_repository.lower():
        return None
    if LINK_BACK_START not in body:
        return None
    return WriterPullRequest(number=listed["number"], url=listed["html_url"], head_branch=head["ref"])


class OpenPullRequestsUnavailable(Exception):
    pass


def is_transient_status(status_code: int) -> bool:
    return status_code >= 500 or status_code == 429


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
        except GITHUB_READ_ERRORS as error:
            logger.warning("knowledge_writer_open_pull_requests_deferred", error_type=type(error).__name__)
            raise OpenPullRequestsUnavailable(type(error).__name__) from error
        if is_transient_status(response.status_code):
            logger.warning("knowledge_writer_open_pull_requests_deferred", status_code=response.status_code)
            raise OpenPullRequestsUnavailable(f"status {response.status_code}")
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


@dataclass(frozen=True)
class PublishedPullRequest:
    repository: str
    number: int


def open_pull_request_for_run(
    task_run_id: UUID, *, team_id: int, is_final_attempt: bool = True
) -> PublishedPullRequest | None:
    writer = writer_settings()
    if writer is None or writer.team_id != team_id:
        log_skipped_publication(task_run_id, team_id, "unconfigured")
        return None
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if run is None or run.task_origin_product != tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER:
        log_skipped_publication(task_run_id, team_id, "not_a_writer_run")
        return None
    published = tasks_facade.read_task_state_entry(run.task_id, team_id, PULL_REQUEST_STATE_KEY)
    if isinstance(published, dict):
        return finish_published_pull_request(
            run, team_id, writer, pull_request_json.validate_python(published), is_final_attempt=is_final_attempt
        )
    return publish_change(run, team_id, writer, is_final_attempt=is_final_attempt)


def log_skipped_publication(task_run_id: UUID, team_id: int, reason: str) -> None:
    logger.info("knowledge_writer_publish_skipped", task_run_id=str(task_run_id), team_id=team_id, reason=reason)


def settle_publication(task_run_id: UUID, *, team_id: int, has_failed: bool) -> None:
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if run is None:
        return
    if has_failed:
        record_pull_request_failure(run.task_id, team_id, "publish_failed")


@dataclass(frozen=True)
class DraftAttempt:
    request: DocsRequest
    task_id: UUID
    task_run_id: UUID
    team_id: int
    changed_files: list[dict] = field(default_factory=list)
    flags: DraftFlags | None = None


def finish_published_pull_request(
    run: TaskRunDTO, team_id: int, writer: WriterSettings, pull_request: WriterPullRequest, *, is_final_attempt: bool
) -> PublishedPullRequest:
    published = PublishedPullRequest(repository=writer.docs_repository, number=pull_request.number)
    if not pull_request.is_review_pending:
        log_skipped_publication(run.id, team_id, "already_published")
        return published
    github = docs_github(team_id, writer.docs_repository.split("/", 1)[0], priority=Priority.CRITICAL)
    if github is None:
        raise WriterPullRequestFailed("knowledge writer lost its docs GitHub integration before requesting review")
    draft = DraftAttempt(
        request=stored_request(tasks_facade.read_task_state_entry(run.task_id, team_id, REQUEST_STATE_KEY)),
        task_id=run.task_id,
        task_run_id=run.id,
        team_id=team_id,
        changed_files=published_changed_files(run, team_id, github, writer.docs_repository),
    )
    request_review_and_capture_opened(github, writer, draft, pull_request, is_final_attempt=is_final_attempt)
    return published


def published_changed_files(
    run: TaskRunDTO, team_id: int, github: GitHubIntegration, docs_repository: str
) -> list[dict]:
    base_sha = tasks_facade.read_task_state_entry(run.task_id, team_id, BASE_SHA_STATE_KEY)
    change = read_writer_change(run, team_id)
    if not isinstance(base_sha, str) or change is None:
        return []
    return changed_files_for(change, base_tree(github, docs_repository, base_sha, change.paths)) or []


def store_pull_request(task_id: UUID, team_id: int, pull_request: WriterPullRequest) -> None:
    stored = pull_request_json.dump_python(pull_request, mode="json")
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_STATE_KEY, replace_entry_with(stored))


def request_review_and_capture_opened(
    github: GitHubIntegration,
    writer: WriterSettings,
    draft: DraftAttempt,
    pull_request: WriterPullRequest,
    *,
    is_final_attempt: bool,
) -> None:
    source = stored_source_change(
        tasks_facade.read_task_state_entry(draft.task_id, draft.team_id, SOURCE_CHANGE_STATE_KEY)
    )
    review = request_author_review(github, writer.docs_repository, pull_request.number, source.author_login)
    if not is_final_attempt and is_transient_review_failure(review):
        raise WriterPullRequestFailed(f"knowledge writer could not request the author's review: {review.status_code}")
    capture_draft(draft, outcome="opened", pull_request_url=pull_request.url, review=review)
    store_pull_request(draft.task_id, draft.team_id, replace(pull_request, is_review_pending=False))


def publish_change(
    run: TaskRunDTO, team_id: int, writer: WriterSettings, *, is_final_attempt: bool
) -> PublishedPullRequest | None:
    task_id, task_run_id = run.task_id, run.id
    request = stored_request(tasks_facade.read_task_state_entry(task_id, team_id, REQUEST_STATE_KEY))
    docs_owner = writer.docs_repository.split("/", 1)[0]
    github = docs_github(team_id, docs_owner, priority=Priority.CRITICAL)
    if github is None:
        logger.warning("knowledge_writer_no_docs_github_integration", team_id=team_id, task_run_id=str(task_run_id))
        record_pull_request_failure(task_id, team_id, "no_github_integration")
        return None
    source_change = stored_source_change(tasks_facade.read_task_state_entry(task_id, team_id, SOURCE_CHANGE_STATE_KEY))
    draft = DraftAttempt(request=request, task_id=task_id, task_run_id=task_run_id, team_id=team_id)
    base_sha = tasks_facade.read_task_state_entry(task_id, team_id, BASE_SHA_STATE_KEY)
    head_branch = tasks_facade.read_task_state_entry(task_id, team_id, HEAD_BRANCH_STATE_KEY)
    if not isinstance(base_sha, str) or not isinstance(head_branch, str):
        refuse_draft(draft, "base_not_recorded")
        return None
    try:
        change = read_writer_change(run, team_id)
    except WriterChangeRefused as refused:
        refuse_draft(draft, refused.reason)
        return None
    if change is None:
        record_pull_request_failure(task_id, team_id, "no_writer_change")
        return None
    if not change.paths:
        refuse_draft(draft, "no_changes")
        return None
    tree = base_tree(github, writer.docs_repository, base_sha, change.paths)
    try:
        changed_files = changed_files_for(change, tree)
    except WriterChangeRefused as refused:
        refuse_draft(draft, refused.reason)
        return None
    if changed_files is None:
        refuse_draft(draft, "unsafe_base_entry")
        return None
    draft = DraftAttempt(
        request=request, task_id=task_id, task_run_id=task_run_id, team_id=team_id, changed_files=changed_files
    )
    docs_folders = docs_folders_for(writer, task_id, team_id)
    publication = publication_check(changed_files, docs_folders, writer.docs_repository, tree.texts, head_texts(change))
    if publication.refusal is not None:
        refuse_draft(draft, publication.refusal)
        return None
    flags = DraftFlags(
        grounding=ground_draft(source_github(team_id, source_change), source_change, changed_files),
        extra_pages=extra_pages(changed_files, docs_folders, routed_page_keys(task_id, team_id)),
        companion_flags=publication.flags,
        rules_flags=publication.rules_flags,
        unrun_enforcers=change.unrun_enforcers,
    )
    draft = replace(draft, flags=flags)
    is_opening_pull_requests = open_pull_requests_flag_state(Team.objects.get(id=team_id))
    if is_opening_pull_requests is None:
        raise WriterPullRequestFailed("knowledge writer could not read the open pull requests flag")
    if not is_opening_pull_requests:
        capture_draft(draft, outcome="logged")
        record_pull_request_failure(task_id, team_id, OPEN_PULL_REQUESTS_OFF)
        return None
    if run.created_at is None:
        refuse_draft(draft, "run_not_dated")
        return None
    author = writer_commit_identity()
    if author is None:
        record_pull_request_failure(task_id, team_id, "no_github_app_slug")
        return None
    commit_sha = build_commit(
        github,
        writer.docs_repository,
        change,
        base_sha,
        author=author,
        committed_at=run.created_at,
        message=f"docs: update for {request.source_url}"[:255],
    )
    if not publish_ref(github, writer.docs_repository, head_branch, commit_sha):
        refuse_draft(draft, "branch_moved")
        return None
    pull_request = open_pull_request(github, writer.docs_repository, request, head_branch, flags)
    if isinstance(pull_request, GitHubStepFailed):
        capture_draft(draft, outcome="failed", refusal=pull_request.step)
        raise reported_step_failure(pull_request, team_id, task_run_id)
    store_pull_request(task_id, team_id, replace(pull_request, is_review_pending=True))
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY, replace_entry_with(None))
    request_review_and_capture_opened(github, writer, draft, pull_request, is_final_attempt=is_final_attempt)
    logger.info(
        "knowledge_writer_pull_request_published",
        task_id=str(task_id),
        task_run_id=str(task_run_id),
        team_id=team_id,
        pull_request_number=pull_request.number,
    )
    return PublishedPullRequest(repository=writer.docs_repository, number=pull_request.number)


@dataclass(frozen=True)
class AuthorReview:
    requested_login: str | None
    skip_reason: str | None = None
    status_code: int | None = None


def request_author_review(
    github: GitHubIntegration, docs_repository: str, pull_request_number: int, author_login: str | None
) -> AuthorReview:
    if author_login is None or author_login.lower() == github_app_login():
        return AuthorReview(requested_login=None, skip_reason=NO_HUMAN_AUTHOR)
    try:
        requested = github.request_pull_request_reviews(docs_repository, pull_request_number, [author_login])
    except Exception:
        logger.warning("knowledge_writer_review_request_raised", pull_request_number=pull_request_number, exc_info=True)
        requested = {"success": False}
    if not requested.get("success") and is_review_requested_from(
        github, docs_repository, pull_request_number, author_login
    ):
        return AuthorReview(requested_login=author_login)
    if not requested.get("success"):
        status_code = requested.get("status_code")
        return AuthorReview(
            requested_login=None,
            skip_reason=REVIEW_REQUEST_FAILED,
            status_code=status_code if isinstance(status_code, int) else None,
        )
    requested_logins = {str(login).lower() for login in requested.get("requested_reviewers") or []}
    if author_login.lower() not in requested_logins:
        return AuthorReview(requested_login=None, skip_reason=REVIEW_REQUEST_REJECTED)
    return AuthorReview(requested_login=author_login)


def is_transient_review_failure(review: AuthorReview) -> bool:
    if review.skip_reason != REVIEW_REQUEST_FAILED:
        return False
    return review.status_code is None or is_transient_status(review.status_code)


def is_review_requested_from(
    github: GitHubIntegration, docs_repository: str, pull_request_number: int, author_login: str
) -> bool:
    try:
        listed = github.get_pull_request(docs_repository, pull_request_number)
    except GITHUB_READ_ERRORS:
        return False
    requested_logins = {str(login).lower() for login in listed.get("requested_reviewers") or []}
    return bool(listed.get("success")) and author_login.lower() in requested_logins


def read_writer_change(run: TaskRunDTO, team_id: int) -> WriterChange | None:
    artifact = writer_change_artifact(run.artifacts)
    if artifact is None:
        return None
    content, _entry, error = tasks_facade.read_task_run_artifact(
        run.id, run.task_id, team_id, storage_path=artifact["storage_path"]
    )
    if content is None:
        raise DocsCommitFailed(f"knowledge writer could not read its change artifact: {error}")
    return parse_writer_change(content)


def changed_files_for(change: WriterChange, tree: BaseTree) -> list[dict] | None:
    ancestors = {directory for path in change.paths for directory in ancestor_directories(path) if directory}
    if any(not is_absent_or_directory(tree.entries.get(directory)) for directory in ancestors):
        return None
    head_by_path = head_texts(change)
    changed_files: list[dict] = []
    for path in sorted(change.paths):
        base_entry = tree.entries.get(path)
        if not is_editable_base_mode(None if base_entry is None else base_entry.mode):
            return None
        if base_entry is None and path in change.deleted:
            return None
        base_text = tree.texts.get(path) if base_entry is not None else ""
        head_text = head_by_path.get(path) if path in change.written else ""
        status = changed_file_status(is_in_base=base_entry is not None, is_deleted=path in change.deleted)
        try:
            changed_files.append(changed_file_entry(path, status, base_text, head_text, change.patches.get(path)))
        except PatchMismatch as mismatch:
            raise WriterChangeRefused("patch_mismatch") from mismatch
    return changed_files


def is_absent_or_directory(entry: BaseEntry | None) -> bool:
    return entry is None or entry.mode == DIRECTORY_MODE


def head_texts(change: WriterChange) -> dict[str, str | None]:
    return {path: decoded_text(content) for path, content in change.written.items()}


def refuse_draft(draft: DraftAttempt, refusal: str) -> None:
    capture_draft(draft, outcome="refused", refusal=refusal)
    refuse_publication(draft.task_id, draft.team_id, draft.task_run_id, refusal)


def capture_draft(
    draft: DraftAttempt,
    *,
    outcome: DraftOutcome,
    refusal: str | None = None,
    pull_request_url: str | None = None,
    review: AuthorReview | None = None,
) -> None:
    flags = draft.flags
    capture_writer_event(
        DRAFT_EVENT,
        team_id=draft.team_id,
        event_key=f"draft:{draft.task_run_id}:{outcome}",
        failure_log="knowledge_writer_draft_capture_failed",
        properties={
            "dedupe_id": draft.request.dedupe_id,
            "source": draft.request.source,
            "source_url": draft.request.source_url,
            "routed_page_urls": list(draft.request.suggested_page_urls),
            "task_id": str(draft.task_id),
            "task_run_id": str(draft.task_run_id),
            "outcome": outcome,
            "refusal": refusal,
            "pull_request_url": pull_request_url,
            "review_requested": review.requested_login if review is not None else None,
            "review_request_skipped": review.skip_reason if review is not None else None,
            "review_request_status_code": review.status_code if review is not None else None,
            "files": drafted_files(draft.changed_files[:MAX_DRAFTED_FILES]),
            "changed_file_count": len(draft.changed_files),
            "are_files_truncated": len(draft.changed_files) > MAX_DRAFTED_FILES,
            "extra_pages": list(flags.extra_pages) if flags is not None else None,
            "unsupported_lines": list(flags.grounding.unsupported_lines[:MAX_GROUNDED_LINES])
            if flags is not None
            else None,
            "grounding_ran": flags.grounding.ran if flags is not None else None,
            "companion_flags": [listed_line(flag) for flag in listed_companion_flags(flags)]
            if flags is not None
            else None,
            "unrun_enforcers": [listed_line(enforcer) for enforcer in flags.unrun_enforcers]
            if flags is not None
            else None,
            "team_id": draft.team_id,
        },
    )


def capture_writer_event(event: str, *, team_id: int, event_key: str, failure_log: str, properties: dict) -> None:
    try:
        send_writer_event(event, team_id=team_id, event_key=event_key, properties=properties, raise_on_error=False)
    except Exception:
        logger.warning(failure_log, team_id=team_id, exc_info=True)


def send_writer_event(event: str, *, team_id: int, event_key: str, properties: dict, raise_on_error: bool) -> None:
    with ph_scoped_capture(raise_on_error=raise_on_error) as capture:
        capture(
            event,
            distinct_id=f"knowledge_writer:{team_id}",
            uuid=uuid.uuid5(uuid.NAMESPACE_URL, f"knowledge_writer:{event_key}"),
            properties=properties,
        )


def drafted_files(changed_files: list[dict]) -> list[dict]:
    drafted: list[dict] = []
    remaining_patch_characters = DRAFT_PATCH_BUDGET_CHARACTERS
    for changed_file in changed_files:
        patch = changed_file.get("patch")
        kept_patch = (
            patch[: min(DRAFT_FILE_PATCH_CHARACTERS, remaining_patch_characters)] if isinstance(patch, str) else ""
        )
        remaining_patch_characters -= len(kept_patch)
        drafted.append(
            {
                "filename": changed_file.get("filename"),
                "status": changed_file.get("status"),
                "patch": kept_patch,
                "is_patch_truncated": isinstance(patch, str) and len(kept_patch) < len(patch),
            }
        )
    return drafted


def docs_folders_for(writer: WriterSettings, task_id: UUID, team_id: int) -> tuple[str, ...]:
    return docs_folders_of(writer, tasks_facade.read_task_state_entry(task_id, team_id, DOCS_CONTENT_ROOT_STATE_KEY))


def publication_check(
    changed_files: list[dict],
    docs_folders: tuple[str, ...],
    docs_repository: str,
    base_texts: Mapping[str, str | None],
    head_texts: Mapping[str, str | None],
) -> CompanionCheck:
    docs_url_path = urlparse(docs_source_for(docs_repository).docs_url_prefix).path
    companion = companion_check(changed_files, docs_folders, docs_url_path, base_texts, head_texts)
    if companion.refusal is not None:
        return companion
    if not all(is_page_source_or_companion(changed_file["filename"]) for changed_file in changed_files):
        return CompanionCheck(refusal="non_page_file", flags=())
    if any(head_text is None for head_text in head_texts.values()):
        return CompanionCheck(refusal="non_text_file", flags=())
    return companion


def is_page_source_or_companion(path: str) -> bool:
    return path.endswith(DOCS_SOURCE_EXTENSIONS) or is_companion_path(path)


def routed_page_keys(task_id: UUID, team_id: int) -> frozenset[str]:
    stored = tasks_facade.read_task_state_entry(task_id, team_id, ROUTED_PAGE_KEYS_STATE_KEY)
    if not isinstance(stored, list):
        return frozenset()
    return frozenset(page_key for page_key in stored if isinstance(page_key, str))


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


def open_pull_request(
    github: GitHubIntegration, docs_repository: str, request: DocsRequest, head_branch: str, flags: DraftFlags
) -> WriterPullRequest | GitHubStepFailed:
    created = github.create_pull_request(
        docs_repository.split("/", 1)[1],
        title=f"docs: update for {request.source_url}"[:255],
        body=pull_request_body(request, flags),
        head_branch=head_branch,
        draft=not flags.is_ready_for_review,
    )
    if created.get("success"):
        return WriterPullRequest(number=created["pr_number"], url=created["pr_url"], head_branch=head_branch)
    already_open = already_open_pull_request(github, docs_repository, head_branch, created)
    if already_open is None:
        return github_step_failed("create_pull_request", created)
    logger.info("knowledge_writer_pull_request_adopted", pull_request_number=already_open.number)
    return already_open


def already_open_pull_request(
    github: GitHubIntegration, docs_repository: str, head_branch: str, created: dict
) -> WriterPullRequest | None:
    if created.get("status_code") != 422:
        return None
    listed = github.get_open_pull_request_for_head(docs_repository, head_branch)
    if listed is None or not isinstance(listed.get("url"), str):
        return None
    return WriterPullRequest(number=listed["number"], url=listed["url"], head_branch=head_branch)


def settle_pull_request(team_id: int, repository: str, pull_request_number: int, *, timed_out: bool) -> bool:
    github = docs_github(team_id, repository.split("/", 1)[0], priority=Priority.NORMAL)
    if github is None:
        raise WriterPullRequestFailed(
            "knowledge writer lost its docs GitHub integration before settling a pull request"
        )
    listed = read_github_json(
        github, f"/repos/{repository}/pulls/{pull_request_number}", endpoint="/repos/{owner}/{repo}/pulls/{pull_number}"
    )
    approval_times = pull_request_approval_times(github, repository, pull_request_number)
    closed = closed_pull_request(github, repository, listed, is_approved=bool(approval_times), timed_out=timed_out)
    if closed is None:
        return False
    close_reason = pull_request_close_reason(github, repository, closed)
    capture_outcome(team_id, repository, closed, close_reason=close_reason, approval_times=approval_times)
    if close_reason != "merged":
        delete_writer_branch(github, team_id, repository, closed)
    return True


def read_github_json(github: GitHubIntegration, path: str, *, endpoint: str, params: dict | None = None) -> object:
    response = github.api_request("GET", path, endpoint=endpoint, params=params)
    if response.status_code != 200:
        raise WriterPullRequestFailed(f"knowledge writer could not read {endpoint}: {response.status_code}")
    return response.json()


def pull_request_approval_times(github: GitHubIntegration, repository: str, pull_request_number: int) -> list[datetime]:
    approval_times: list[datetime] = []
    for page in range(1, MAX_REVIEW_PAGES + 1):
        reviews = read_github_json(
            github,
            f"/repos/{repository}/pulls/{pull_request_number}/reviews",
            endpoint="/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            params={"per_page": REVIEWS_PER_PAGE, "page": page},
        )
        if not isinstance(reviews, list):
            return approval_times
        approval_times.extend(
            github_time(review["submitted_at"])
            for review in reviews
            if review.get("state") == "APPROVED"
            and review.get("submitted_at")
            and review.get("author_association") in MAINTAINER_ASSOCIATIONS
        )
        if len(reviews) < REVIEWS_PER_PAGE:
            return approval_times
    return approval_times


def closed_pull_request(
    github: GitHubIntegration, repository: str, listed: object, *, is_approved: bool, timed_out: bool
) -> dict | None:
    if not isinstance(listed, dict):
        raise WriterPullRequestFailed("knowledge writer read a pull request that is not an object")
    if listed.get("state") == "closed":
        return listed
    if not timed_out or is_approved:
        return None
    closed = github.api_request(
        "PATCH",
        f"/repos/{repository}/pulls/{listed['number']}",
        endpoint="/repos/{owner}/{repo}/pulls/{pull_number}",
        json_body={"state": "closed"},
    )
    if closed.status_code != 200:
        raise WriterPullRequestFailed(f"knowledge writer could not close a stale pull request: {closed.status_code}")
    return closed.json()


def pull_request_close_reason(github: GitHubIntegration, repository: str, closed: dict) -> CloseReason:
    if closed.get("merged") is True or closed.get("merged_at"):
        return "merged"
    issue = read_github_json(
        github,
        f"/repos/{repository}/issues/{closed['number']}",
        endpoint="/repos/{owner}/{repo}/issues/{issue_number}",
    )
    closed_by = str(((issue if isinstance(issue, dict) else {}).get("closed_by") or {}).get("login", "")).lower()
    app_login = github_app_login()
    if app_login is not None and closed_by == app_login:
        return "closed_stale"
    return "closed_by_reviewer"


def delete_writer_branch(github: GitHubIntegration, team_id: int, repository: str, closed: dict) -> None:
    head = closed.get("head") or {}
    head_branch = str(head.get("ref") or "")
    head_repository = str((head.get("repo") or {}).get("full_name", "")).lower()
    if not head_branch.startswith(HEAD_BRANCH_PREFIX) or head_repository != repository.lower():
        return
    deleted = github.api_request(
        "DELETE",
        f"/repos/{repository}/git/refs/heads/{quote(head_branch, safe='/')}",
        endpoint="/repos/{owner}/{repo}/git/refs/heads/{branch}",
    )
    if deleted.status_code in (204, 404, 422):
        return
    logger.warning(
        "knowledge_writer_closed_branch_delete_failed",
        team_id=team_id,
        pull_request_number=closed["number"],
        status_code=deleted.status_code,
    )
    capture_exception(
        WriterPullRequestFailed("knowledge writer could not delete a closed branch"),
        {"team_id": team_id, "pull_request_number": closed["number"], "status_code": deleted.status_code},
    )


def capture_outcome(
    team_id: int, repository: str, closed: dict, *, close_reason: CloseReason, approval_times: list[datetime]
) -> None:
    opened_at = github_time(closed["created_at"])
    first_approval_at = min(approval_times, default=None)
    send_writer_event(
        OUTCOME_EVENT,
        team_id=team_id,
        event_key=f"outcome:{repository.lower()}#{closed['number']}",
        raise_on_error=True,
        properties={
            "pull_request_url": closed.get("html_url"),
            "merged": close_reason == "merged",
            "approved": first_approval_at is not None,
            "hours_to_first_approval": hours_between(opened_at, first_approval_at)
            if first_approval_at is not None
            else None,
            "hours_open": hours_between(opened_at, github_time(closed["closed_at"])),
            "close_reason": close_reason,
        },
    )


def github_time(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp)


def hours_between(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / SECONDS_PER_HOUR, 2)
