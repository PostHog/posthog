from datetime import datetime, timedelta
from uuid import UUID

from django.utils import timezone

from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

from ..facade.contracts import DocsRequest

REQUEST_STATE_KEY = "knowledge_writer_request"
SECTION_STATE_KEY = "knowledge_writer_section"
JOIN_STATE_KEY = "knowledge_writer_join"
HEAD_BRANCH_STATE_KEY = "knowledge_writer_head_branch"
PULL_REQUEST_STATE_KEY = "knowledge_writer_pull_request"
PULL_REQUEST_FAILURE_STATE_KEY = "knowledge_writer_pull_request_failure"
PUBLICATION_CLAIM_STATE_KEY = "knowledge_writer_publication_claim"
PUBLICATION_LEASE = timedelta(minutes=30)
BRANCH_REFUSALS = frozenset({"changed_paths_outside_docs", "too_many_changed_files"})


def publication_claim(task_run_id: UUID) -> dict[str, str]:
    return {"task_run_id": str(task_run_id), "claimed_at": timezone.now().isoformat()}


def publication_claim_owner(claim: object) -> str | None:
    if not isinstance(claim, dict):
        return None
    owner = claim.get("task_run_id")
    return owner if isinstance(owner, str) else None


def is_publication_claim_live(claim: object) -> bool:
    if not isinstance(claim, dict) or publication_claim_owner(claim) is None:
        return False
    try:
        claimed_at = datetime.fromisoformat(claim["claimed_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return timezone.now() - claimed_at < PUBLICATION_LEASE


@dataclass(frozen=True)
class WriterPullRequest:
    number: int
    url: str
    head_branch: str
    section: str | None


request_json = TypeAdapter(DocsRequest)
pull_request_json = TypeAdapter(WriterPullRequest)
