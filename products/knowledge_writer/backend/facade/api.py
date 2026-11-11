from collections.abc import Mapping
from typing import Any

from posthog.github.installations import installation_id

from ...merge_check.sources import merged_pull_request_change
from ..adapters.registry import REGISTRY
from ..logic import intake
from ..settings import configured_writer_team_id, source_repositories, writer_settings
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

    change = merged_pull_request_change(payload, source_repositories())
    team_id = configured_writer_team_id()
    delivery_installation_id = installation_id(dict(payload))
    if change is None or team_id is None or delivery_installation_id is None:
        return
    start_merge_check(change, team_id=team_id, installation_id=delivery_installation_id)
