from collections.abc import Mapping
from typing import Any

from posthog.github.installations import installation_team_ids

from ...merge_check.sources import landed_change
from ..adapters.registry import REGISTRY
from ..logic import intake
from ..settings import source_repositories, writer_settings
from .contracts import DocsCommandRequest, IntakeOutcome
from .enums import DocsRequestSource


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None


def request_docs_for_pull_request(command: DocsCommandRequest, *, team_id: int) -> IntakeOutcome:
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(command)
    return intake.submit(verdict, team_id=team_id)


def record_default_branch_push(payload: Mapping[str, Any]) -> None:
    from ..temporal.client import start_merge_check  # noqa: PLC0415 — keeps temporalio off the facade import path

    change = landed_change(payload, source_repositories())
    if change is None:
        return
    writer = writer_settings()
    if writer is None or writer.team_id not in installation_team_ids(dict(payload)):
        return
    start_merge_check(change, team_id=writer.team_id)
