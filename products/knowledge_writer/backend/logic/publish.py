from uuid import UUID

import structlog
from pydantic import TypeAdapter

from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration

from products.tasks.backend.facade import api as tasks_facade

from ..facade.contracts import DocsRequest
from ..settings import writer_settings
from .launch import REQUEST_STATE_KEY

logger = structlog.get_logger(__name__)

PULL_REQUEST_STATE_KEY = "knowledge_writer_pull_request"
LINK_BACK_START = "<!-- knowledge-writer-sources -->"
LINK_BACK_END = "<!-- /knowledge-writer-sources -->"

_request_json = TypeAdapter(DocsRequest)


def docs_head_branch(output: object, docs_repository: str) -> str | None:
    for head in tasks_facade.read_head_branches(output):
        if head["repository"] == docs_repository.lower():
            return head["branch"]
    return None


def link_back_block(source_urls: list[str]) -> str:
    lines = [f"- {source_url}" for source_url in source_urls]
    return "\n".join([LINK_BACK_START, *lines, LINK_BACK_END])


def pull_request_body(request: DocsRequest) -> str:
    requester = f" for {request.requested_by}" if request.requested_by else ""
    return f"The knowledge writer opened this{requester}.\n\n{link_back_block([request.source_url])}"


def docs_github(team_id: int, docs_owner: str) -> GitHubIntegration | None:
    for integration in Integration.objects.filter(team_id=team_id, kind="github").order_by("id"):
        if str(integration.config.get("account", {}).get("name", "")).lower() == docs_owner.lower():
            return GitHubIntegration(integration, source="knowledge_writer", priority=Priority.CRITICAL)
    return None


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
    opened_url = tasks_facade.read_task_state_entry(run.task_id, team_id, PULL_REQUEST_STATE_KEY)
    if isinstance(opened_url, str):
        return opened_url
    request = _request_json.validate_python(tasks_facade.read_task_state_entry(run.task_id, team_id, REQUEST_STATE_KEY))
    docs_owner, docs_name = writer.docs_repository.split("/", 1)
    github = docs_github(team_id, docs_owner)
    if github is None:
        logger.warning("knowledge_writer_no_docs_github_integration", team_id=team_id, task_run_id=str(task_run_id))
        return None
    created = github.create_pull_request(
        docs_name,
        title=f"docs: update for {request.source_url}"[:255],
        body=pull_request_body(request),
        head_branch=head_branch,
    )
    if not created.get("success"):
        logger.warning(
            "knowledge_writer_pull_request_failed",
            team_id=team_id,
            task_run_id=str(task_run_id),
            status_code=created.get("status_code"),
        )
        return None
    pull_request_url = created["pr_url"]
    tasks_facade.update_task_state_entry(
        run.task_id, team_id, PULL_REQUEST_STATE_KEY, lambda _current: (pull_request_url, None)
    )
    return pull_request_url
