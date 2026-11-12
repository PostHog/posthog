from collections.abc import Mapping
from typing import Any

import structlog

from posthog.github.installations import installation_id

from ...merge_check.sources import LandedChange, merged_pull_request_change
from ..adapters.registry import REGISTRY
from ..logic import intake
from ..settings import configured_writer_team_id, source_repositories, writer_settings
from .contracts import DocsCommandRequest, IntakeOutcome
from .enums import DocsRequestSource

logger = structlog.get_logger(__name__)


def writer_team_id() -> int | None:
    writer = writer_settings()
    return writer.team_id if writer else None


def request_docs_for_pull_request(command: DocsCommandRequest, *, team_id: int) -> IntakeOutcome:
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(command)
    return intake.submit(verdict, team_id=team_id)


def record_merged_pull_request(payload: Mapping[str, Any]) -> None:
    from ..temporal.client import start_merge_check  # noqa: PLC0415 — keeps temporalio off the facade import path

    watched_repositories = source_repositories()
    change = merged_pull_request_change(payload, watched_repositories)
    team_id = configured_writer_team_id()
    delivery_installation_id = installation_id(dict(payload))
    if change is None or team_id is None or delivery_installation_id is None:
        _log_skipped_merge_delivery(payload, watched_repositories, reason=_merge_delivery_skip_reason(change, team_id))
        return
    start_merge_check(change, team_id=team_id, installation_id=delivery_installation_id)


def _merge_delivery_skip_reason(change: LandedChange | None, team_id: int | None) -> str:
    if change is None:
        return "not_a_source_merge"
    if team_id is None:
        return "no_writer_team"
    return "no_installation"


def _log_skipped_merge_delivery(
    payload: Mapping[str, Any], watched_repositories: tuple[str, ...], *, reason: str
) -> None:
    pull_request = payload.get("pull_request") or {}
    repository = (payload.get("repository") or {}).get("full_name")
    is_watched_repository = isinstance(repository, str) and repository.lower() in {
        name.lower() for name in watched_repositories
    }
    if not is_watched_repository or payload.get("action") != "closed" or pull_request.get("merged") is not True:
        return
    logger.info(
        "knowledge_writer_merge_delivery_skipped",
        repository=repository,
        pull_request_number=pull_request.get("number"),
        reason=reason,
    )
