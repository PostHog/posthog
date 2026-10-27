import re

from ..adapters import REGISTRY
from ..logic import intake
from ..settings import writer_settings
from .contracts import DocsCommandRequest, IntakeOutcome, MergeCheckReport
from .enums import DocsRequestSource

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None


def request_docs_for_pull_request(command: DocsCommandRequest, *, team_id: int) -> IntakeOutcome:
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(command)
    return intake.submit(verdict, team_id=team_id)


def submit_merge_report(report: MergeCheckReport, *, team_id: int) -> IntakeOutcome:
    from ..temporal.client import (  # noqa: PLC0415 — keeps temporalio off the facade import path
        VERDICT_RECORDED,
        signal_merge_backstop,
    )

    outcome = intake.submit(REGISTRY[DocsRequestSource.REPO_MERGE].assess(report), team_id=team_id)
    signal_merge_backstop(report.commit_sha, team_id=team_id, signal=VERDICT_RECORDED)
    return outcome


def record_merge_push(commit_sha: str) -> None:
    from ..temporal.client import (  # noqa: PLC0415 — keeps temporalio off the facade import path
        PUSH_SEEN,
        signal_merge_backstop,
    )

    team_id = writer_team_id()
    if team_id is None or not COMMIT_SHA_PATTERN.match(commit_sha):
        return
    signal_merge_backstop(commit_sha, team_id=team_id, signal=PUSH_SEEN)
