import uuid
import difflib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal
from urllib.parse import urlparse
from uuid import UUID

import structlog

from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationManager
from posthog.models.instance_setting import get_instance_setting
from posthog.models.integration import GitHubIntegration
from posthog.models.team import Team
from posthog.ph_client import ph_scoped_capture

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.contracts import TaskRunDTO

from ..facade.contracts import DocsRequest
from ..feature_flags import open_pull_requests_flag_state
from ..settings import DEFAULT_DOCS_PATHS, WriterSettings, docs_source_for, writer_settings
from .docs_pages import DOCS_SOURCE_EXTENSIONS, are_only_page_redirects_changed, docs_page_key, is_nav_line
from .launch import replace_entry_with
from .records import (
    BASE_SHA_STATE_KEY,
    DOCS_CONTENT_ROOT_STATE_KEY,
    HEAD_BRANCH_STATE_KEY,
    PULL_REQUEST_FAILURE_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    REQUEST_STATE_KEY,
    SOURCE_CHANGE_STATE_KEY,
    WriterPullRequest,
    pull_request_json,
    stored_request,
    stored_source_change,
)
from .routing import SOURCE_REPOSITORY
from .server_commit import (
    DIRECTORY_MODE,
    REGULAR_FILE_MODE,
    BaseEntry,
    BaseTree,
    CommitIdentity,
    DocsCommitFailed,
    ancestor_directories,
    base_tree,
    build_commit,
    publish_ref,
)
from .writer_change import WriterChange, WriterChangeRefused, parse_writer_change, writer_change_artifact

logger = structlog.get_logger(__name__)

LINK_BACK_START = "<!-- knowledge-writer-sources -->"
LINK_BACK_END = "<!-- /knowledge-writer-sources -->"
PULL_REQUESTS_PER_PAGE = 100
MAX_PULL_REQUEST_PAGES = 20
DRAFT_EVENT = "knowledge_writer draft"
DRAFT_FILE_PATCH_CHARACTERS = 4_000
DRAFT_PATCH_BUDGET_CHARACTERS = 60_000
OPEN_PULL_REQUESTS_OFF = "open_pull_requests_off"
NO_HUMAN_AUTHOR = "no_human_author"
REVIEW_REQUEST_FAILED = "review_request_failed"
REVIEW_REQUEST_REJECTED = "review_request_rejected"
DraftOutcome = Literal["refused", "logged", "opened", "failed"]


def link_back_block(source_urls: list[str]) -> str:
    lines = [f"- {source_url}" for source_url in source_urls]
    return "\n".join([LINK_BACK_START, *lines, LINK_BACK_END])


def pull_request_body(request: DocsRequest) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    return f"The knowledge writer opened this{requester}.\n\n{link_back_block([request.source_url])}"


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


def open_pull_request_for_run(task_run_id: UUID, *, team_id: int) -> str | None:
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
        return finish_published_pull_request(run, team_id, writer, pull_request_json.validate_python(published))
    return publish_change(run, team_id, writer)


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


def finish_published_pull_request(
    run: TaskRunDTO, team_id: int, writer: WriterSettings, pull_request: WriterPullRequest
) -> str:
    if not pull_request.is_review_pending:
        log_skipped_publication(run.id, team_id, "already_published")
        return pull_request.url
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
    request_review_and_capture_opened(github, writer, draft, pull_request)
    return pull_request.url


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
    github: GitHubIntegration, writer: WriterSettings, draft: DraftAttempt, pull_request: WriterPullRequest
) -> None:
    source = stored_source_change(
        tasks_facade.read_task_state_entry(draft.task_id, draft.team_id, SOURCE_CHANGE_STATE_KEY)
    )
    review = request_author_review(github, writer.docs_repository, pull_request.number, source.author_login)
    capture_draft(draft, outcome="opened", pull_request_url=pull_request.url, review=review)
    store_pull_request(draft.task_id, draft.team_id, replace(pull_request, is_review_pending=False))


def publish_change(run: TaskRunDTO, team_id: int, writer: WriterSettings) -> str | None:
    task_id, task_run_id = run.task_id, run.id
    request = stored_request(tasks_facade.read_task_state_entry(task_id, team_id, REQUEST_STATE_KEY))
    docs_owner, docs_name = writer.docs_repository.split("/", 1)
    github = docs_github(team_id, docs_owner, priority=Priority.CRITICAL)
    if github is None:
        logger.warning("knowledge_writer_no_docs_github_integration", team_id=team_id, task_run_id=str(task_run_id))
        record_pull_request_failure(task_id, team_id, "no_github_integration")
        return None
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
    changed_files = changed_files_for(change, tree)
    if changed_files is None:
        refuse_draft(draft, "unsafe_base_entry")
        return None
    draft = DraftAttempt(
        request=request, task_id=task_id, task_run_id=task_run_id, team_id=team_id, changed_files=changed_files
    )
    refusal = publication_refusal(
        changed_files,
        docs_folders_for(writer, task_id, team_id),
        writer.docs_repository,
        tree.texts,
        head_texts(change),
    )
    if refusal is not None:
        refuse_draft(draft, refusal)
        return None
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
    pull_request = open_pull_request(github, docs_name, request, head_branch)
    if isinstance(pull_request, GitHubStepFailed):
        capture_draft(draft, outcome="failed", refusal=pull_request.step)
        raise reported_step_failure(pull_request, team_id, task_run_id)
    store_pull_request(task_id, team_id, replace(pull_request, is_review_pending=True))
    tasks_facade.update_task_state_entry(task_id, team_id, PULL_REQUEST_FAILURE_STATE_KEY, replace_entry_with(None))
    request_review_and_capture_opened(github, writer, draft, pull_request)
    logger.info(
        "knowledge_writer_pull_request_published",
        task_id=str(task_id),
        task_run_id=str(task_run_id),
        team_id=team_id,
        pull_request_number=pull_request.number,
    )
    return pull_request.url


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
        return AuthorReview(requested_login=None, skip_reason=REVIEW_REQUEST_FAILED)
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
        if base_entry is not None and base_entry.mode != REGULAR_FILE_MODE:
            return None
        if base_entry is None and path in change.deleted:
            return None
        base_text = tree.texts.get(path) if base_entry is not None else ""
        head_text = head_by_path.get(path) if path in change.written else ""
        changed_files.append(
            {
                "filename": path,
                "status": file_status(path, change, is_in_base=base_entry is not None),
                "patch": text_patch(base_text, head_text),
            }
        )
    return changed_files


def is_absent_or_directory(entry: BaseEntry | None) -> bool:
    return entry is None or entry.mode == DIRECTORY_MODE


def file_status(path: str, change: WriterChange, *, is_in_base: bool) -> str:
    if path in change.deleted:
        return "removed"
    return "modified" if is_in_base else "added"


def head_texts(change: WriterChange) -> dict[str, str | None]:
    return {path: decoded_text(content) for path, content in change.written.items()}


def decoded_text(content: bytes) -> str | None:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return None


def text_patch(base_text: str | None, head_text: str | None) -> str | None:
    if base_text is None or head_text is None:
        return None
    hunks = difflib.unified_diff(git_lines(base_text), git_lines(head_text), lineterm="")
    return "\n".join(list(hunks)[2:])


def git_lines(text: str) -> list[str]:
    lines = text.split("\n")
    return lines[:-1] if lines[-1] == "" else lines


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
    capture_writer_event(
        DRAFT_EVENT,
        team_id=draft.team_id,
        event_key=f"draft:{draft.task_run_id}",
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
            "files": drafted_files(draft.changed_files),
            "team_id": draft.team_id,
        },
    )


def capture_writer_event(event: str, *, team_id: int, event_key: str, failure_log: str, properties: dict) -> None:
    try:
        with ph_scoped_capture() as capture:
            capture(
                event,
                distinct_id=f"knowledge_writer:{team_id}",
                uuid=uuid.uuid5(uuid.NAMESPACE_URL, f"knowledge_writer:{event_key}"),
                properties=properties,
            )
    except Exception:
        logger.warning(failure_log, team_id=team_id, exc_info=True)


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


PAGE_CHANGING_STATUSES = frozenset({"added", "removed"})
COMPANION_PATHS = frozenset({"vercel.json", "src/navs/index.js"})
MAX_COMPANION_PATCH_CHARACTERS = 16_384


def docs_folders_for(writer: WriterSettings, task_id: UUID, team_id: int) -> tuple[str, ...]:
    if writer.docs_paths:
        return writer.docs_paths
    stored_root = tasks_facade.read_task_state_entry(task_id, team_id, DOCS_CONTENT_ROOT_STATE_KEY)
    content_root = stored_root.strip("/") if isinstance(stored_root, str) else ""
    return (content_root or DEFAULT_DOCS_PATHS.strip("/"),)


def publication_refusal(
    changed_files: list[dict],
    docs_folders: tuple[str, ...],
    docs_repository: str,
    base_texts: Mapping[str, str | None],
    head_texts: Mapping[str, str | None],
) -> str | None:
    outside_docs_refusal = companion_refusal(changed_files, docs_folders, docs_repository, base_texts, head_texts)
    if outside_docs_refusal is not None:
        return outside_docs_refusal
    if not all(is_page_source_or_companion(changed_file["filename"]) for changed_file in changed_files):
        return "non_page_file"
    if any(head_text is None for head_text in head_texts.values()):
        return "non_text_file"
    return None


def is_page_source_or_companion(path: str) -> bool:
    return path.endswith(DOCS_SOURCE_EXTENSIONS) or path in COMPANION_PATHS


def companion_refusal(
    changed_files: list[dict],
    docs_folders: tuple[str, ...],
    docs_repository: str,
    base_texts: Mapping[str, str | None],
    head_texts: Mapping[str, str | None],
) -> str | None:
    companion_files = [
        changed_file for changed_file in changed_files if not is_docs_path(changed_file["filename"], docs_folders)
    ]
    if not companion_files:
        return None
    docs_url_path = urlparse(docs_source_for(docs_repository).docs_url_prefix).path
    page_paths = frozenset(f"{docs_url_path}{page_key}" for page_key in changed_page_keys(changed_files, docs_folders))
    if not page_paths or not all(is_listed_companion(changed_file) for changed_file in companion_files):
        return "changed_paths_outside_docs"
    redirect_files = [changed_file for changed_file in companion_files if changed_file["filename"].endswith(".json")]
    nav_files = [changed_file for changed_file in companion_files if changed_file not in redirect_files]
    if not all(
        is_nav_line(line, page_paths) for changed_file in nav_files for line in changed_lines(changed_file["patch"])
    ):
        return "changed_paths_outside_docs"
    if not all(
        are_only_page_redirects_changed(
            base_texts.get(changed_file["filename"]),
            head_texts.get(changed_file["filename"]),
            page_paths,
            docs_url_path,
        )
        for changed_file in redirect_files
    ):
        return "changed_paths_outside_docs"
    return None


def is_docs_path(path: str, docs_paths: tuple[str, ...]) -> bool:
    return any(path == docs_path or path.startswith(f"{docs_path}/") for docs_path in docs_paths)


def changed_page_keys(changed_files: list[dict], docs_paths: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        page_key
        for changed_file in changed_files
        if changed_file.get("status") in PAGE_CHANGING_STATUSES
        for docs_path in docs_paths
        if (page_key := docs_page_key(changed_file["filename"], docs_path)) is not None
    )


def is_listed_companion(changed_file: dict) -> bool:
    patch = changed_file.get("patch")
    return (
        changed_file["filename"] in COMPANION_PATHS
        and changed_file.get("status") == "modified"
        and isinstance(patch, str)
        and len(patch) <= MAX_COMPANION_PATCH_CHARACTERS
    )


def changed_lines(patch: str) -> list[str]:
    return [line[1:] for line in patch.split("\n") if line[:1] in ("+", "-")]


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
    github: GitHubIntegration, docs_name: str, request: DocsRequest, head_branch: str
) -> WriterPullRequest | GitHubStepFailed:
    created = github.create_pull_request(
        docs_name,
        title=f"docs: update for {request.source_url}"[:255],
        body=pull_request_body(request),
        head_branch=head_branch,
        draft=True,
    )
    if not created.get("success"):
        return github_step_failed("create_pull_request", created)
    return WriterPullRequest(number=created["pr_number"], url=created["pr_url"], head_branch=head_branch)
