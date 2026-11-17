from pydantic import TypeAdapter
from pydantic.dataclasses import dataclass

from ..facade.contracts import DocsRequest

REQUEST_STATE_KEY = "knowledge_writer_request"
HEAD_BRANCH_STATE_KEY = "knowledge_writer_head_branch"
BASE_SHA_STATE_KEY = "knowledge_writer_base_sha"
PULL_REQUEST_STATE_KEY = "knowledge_writer_pull_request"
PULL_REQUEST_FAILURE_STATE_KEY = "knowledge_writer_pull_request_failure"
DOCS_CONTENT_ROOT_STATE_KEY = "knowledge_writer_docs_content_root"


@dataclass(frozen=True)
class WriterPullRequest:
    number: int
    url: str
    head_branch: str


request_json = TypeAdapter(DocsRequest)
pull_request_json = TypeAdapter(WriterPullRequest)


def stored_request(entry: object) -> DocsRequest:
    if isinstance(entry, dict):
        # TODO: remove once writer tasks stored before skip_judge was dropped have all published.
        entry = {key: value for key, value in entry.items() if key != "skip_judge"}
    return request_json.validate_python(entry)
