from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

from ..facade.contracts import DocsRequest

REQUEST_STATE_KEY = "knowledge_writer_request"
SECTION_STATE_KEY = "knowledge_writer_section"
JOIN_STATE_KEY = "knowledge_writer_join"
PULL_REQUEST_STATE_KEY = "knowledge_writer_pull_request"
PULL_REQUEST_FAILURE_STATE_KEY = "knowledge_writer_pull_request_failure"
PUBLICATION_CLAIM_STATE_KEY = "knowledge_writer_publication_claim"


@dataclass(frozen=True)
class WriterPullRequest:
    number: int
    url: str
    head_branch: str
    section: str | None


request_json = TypeAdapter(DocsRequest)
pull_request_json = TypeAdapter(WriterPullRequest)
