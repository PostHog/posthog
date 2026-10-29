import re

from ..settings import writer_settings
from .contracts import CommandCheckStatus, DocsCommandRequest

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None


def request_docs_for_pull_request(command: DocsCommandRequest, *, team_id: int) -> CommandCheckStatus:
    from ..temporal.client import start_merge_check  # noqa: PLC0415 — keeps temporalio off the facade import path
    from ..temporal.merge_workflow import MergeCheckCommand, MergeCheckInputs  # noqa: PLC0415 — same

    inputs = MergeCheckInputs(
        commit_sha=None,
        team_id=team_id,
        repository=command.repository,
        command=MergeCheckCommand(
            pull_request_number=command.pull_request_number,
            pull_request_url=command.pull_request_url,
            head_sha=command.head_sha,
            note=command.note,
            requested_by=command.requested_by,
            requested_by_user_id=command.requested_by_user_id,
        ),
    )
    return "queued" if start_merge_check(inputs) else "duplicate"


def record_merge_push(commit_sha: str) -> None:
    from ..temporal.client import start_merge_check  # noqa: PLC0415 — keeps temporalio off the facade import path
    from ..temporal.merge_workflow import MergeCheckInputs  # noqa: PLC0415 — same

    team_id = writer_team_id()
    if team_id is None or not COMMIT_SHA_PATTERN.match(commit_sha):
        return
    start_merge_check(MergeCheckInputs(commit_sha=commit_sha, team_id=team_id))
