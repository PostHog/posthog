from dataclasses import replace
from uuid import UUID

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import DocsRequest

REQUEST_STATE_KEY = "knowledge_writer_request"
HEAD_BRANCH_STATE_KEY = "knowledge_writer_head_branch"
BASE_SHA_STATE_KEY = "knowledge_writer_base_sha"
PULL_REQUEST_STATE_KEY = "knowledge_writer_pull_request"
PULL_REQUEST_FAILURE_STATE_KEY = "knowledge_writer_pull_request_failure"
DOCS_CONTENT_ROOT_STATE_KEY = "knowledge_writer_docs_content_root"
SOURCE_CHANGE_STATE_KEY = "knowledge_writer_source_change"
ROUTED_PAGE_KEYS_STATE_KEY = "knowledge_writer_routed_page_keys"
# Written only by the held-request intake this release removed; delete once no task state holds it.
LEGACY_HELD_REQUESTS_STATE_KEY = "knowledge_writer_held_requests"
SOURCE_CHANGE_FIELDS = frozenset({"source_repository", "source_commit_sha", "source_author_login"})


@dataclass(frozen=True)
class WriterPullRequest:
    number: int
    url: str
    head_branch: str
    is_review_pending: bool = False


@dataclass(frozen=True)
class SourceChange:
    repository: str | None = None
    commit_sha: str | None = None
    author_login: str | None = None


request_json = TypeAdapter(DocsRequest)
pull_request_json = TypeAdapter(WriterPullRequest)
source_change_json = TypeAdapter(SourceChange)


def stored_request(entry: object) -> DocsRequest:
    if isinstance(entry, dict):
        # TODO: remove once writer tasks stored before skip_judge was dropped have all published.
        entry = {key: value for key, value in entry.items() if key != "skip_judge"}
    return request_json.validate_python(entry)


def source_change_of(request: DocsRequest) -> SourceChange:
    return SourceChange(
        repository=request.source_repository,
        commit_sha=request.source_commit_sha,
        author_login=request.source_author_login,
    )


def stored_source_change(entry: object) -> SourceChange:
    if not isinstance(entry, dict):
        return SourceChange()
    return source_change_json.validate_python(entry)


def task_request(task_id: UUID, team_id: int) -> DocsRequest:
    request = stored_request(tasks_facade.read_task_state_entry(task_id, team_id, REQUEST_STATE_KEY))
    docs_content_root = tasks_facade.read_task_state_entry(task_id, team_id, DOCS_CONTENT_ROOT_STATE_KEY)
    stored_change = tasks_facade.read_task_state_entry(task_id, team_id, SOURCE_CHANGE_STATE_KEY)
    source_change = (
        stored_source_change(stored_change) if isinstance(stored_change, dict) else source_change_of(request)
    )
    return replace(
        request,
        docs_content_root=docs_content_root if isinstance(docs_content_root, str) else None,
        source_repository=source_change.repository,
        source_commit_sha=source_change.commit_sha,
        source_author_login=source_change.author_login,
    )
