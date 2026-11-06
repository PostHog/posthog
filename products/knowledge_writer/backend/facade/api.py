from collections.abc import Mapping
from typing import Any

from posthog.github.installations import installation_team_ids

from ...merge_check.sources import POSTHOG_REPOSITORY, merged_mainline_commit
from ..adapters.registry import REGISTRY
from ..logic import intake
from ..settings import writer_settings
from .contracts import DocsCommandRequest, IntakeOutcome
from .enums import DocsRequestSource


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None


def request_docs_for_pull_request(command: DocsCommandRequest, *, team_id: int) -> IntakeOutcome:
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(command)
    return intake.submit(verdict, team_id=team_id)


def record_merged_pull_request(payload: Mapping[str, Any]) -> None:
    from ..temporal.client import start_merge_check  # noqa: PLC0415 — keeps temporalio off the facade import path

    if payload.get("action") != "closed":
        return
    if (payload.get("repository") or {}).get("full_name") != POSTHOG_REPOSITORY:
        return
    commit_sha = merged_mainline_commit(payload.get("pull_request") or {})
    if commit_sha is None:
        return
    team_id = writer_team_id()
    if team_id is None or team_id not in installation_team_ids(dict(payload)):
        return
    start_merge_check(commit_sha, team_id=team_id)
