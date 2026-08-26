"""Repository selection for Signals reports.

Thin wrapper around `products.tasks.backend.logic.repo_selection.select_repository`.
Renders `SignalData` to text and collapses both `RepoSelectionRejectedError`
(LLM hallucination) and `RepoSelectionUnavailableError` (no eligible repos)
into `RepoSelectionResult(repository=None, ...)` — Signals has no picker
fallback, so the shared module's operational-vs-semantic distinction has
nowhere to land; `summary.py` treats `repository=None` as
``REQUIRES_HUMAN_INPUT``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from posthog.sync import database_sync_to_async

from products.signals.backend.agent_runtime import STEP_REPO_SELECTION, resolve_agent_runtime
from products.signals.backend.models import SignalReportArtefact
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.facade.repo_selection import (
    REPO_SELECTION_DUMMY_REPOSITORY,
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
    resolve_team_github_integration,
    select_repository,
)

if TYPE_CHECKING:
    # Deferred (see _select below): importing temporal.types runs the signals temporal package
    # __init__ (agentic -> back into report_generation), a circular import. SignalData is
    # annotation-only here (module uses `from __future__ import annotations`).
    from products.signals.backend.temporal.types import SignalData
    from products.tasks.backend.facade.agents import OutputFn

logger = logging.getLogger(__name__)

__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "persisted_repo_selection",
    "resolve_team_github_integration",
    "select_repository_for_report",
    "select_repository_for_team",
]


def persisted_repo_selection(report_id: str) -> RepoSelectionResult | None:
    """The report's latest ``repo_selection`` artefact, or ``None`` if it has none yet.

    A result with ``repository=None`` is a deliberate no-repo decision (nothing to fix in code),
    not "unresolved" — callers must not treat the two the same.
    """
    artefact = (
        SignalReportArtefact.objects.filter(report_id=report_id, type=SignalReportArtefact.ArtefactType.REPO_SELECTION)
        .order_by("-created_at")
        .first()
    )
    if artefact is None:
        return None
    return RepoSelectionResult.model_validate_json(artefact.content)


async def select_repository_for_team(
    team_id: int,
    user_id: int,
    request_section: str,
    *,
    step_name: str = "repo_selection",
    signal_report_id: str | None = None,
    sandbox_environment_id: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> RepoSelectionResult:
    """Select the most relevant repository for a free-form request against the team's repos.

    ``request_section`` is the caller-rendered string describing the request (e.g. rendered
    signals or a custom agent's initial prompt). Both rejection (LLM hallucination) and
    unavailability (no eligible repos) collapse into ``RepoSelectionResult(repository=None, ...)``
    — Signals/custom agents have no picker fallback, so callers treat ``repository=None`` as
    "no match / requires human input".
    """
    # Resolved at the single repo-selection chokepoint so both callers (custom agent +
    # report flow) pick it up.
    agent_runtime = await database_sync_to_async(resolve_agent_runtime, thread_sensitive=False)(
        team_id, STEP_REPO_SELECTION
    )
    try:
        return await select_repository(
            team_id=team_id,
            user_id=user_id,
            context=request_section,
            origin_product=tasks_facade.TaskOriginProduct.SIGNAL_REPORT,
            step_name=step_name,
            signal_report_id=signal_report_id,
            sandbox_environment_id=sandbox_environment_id,
            verbose=verbose,
            output_fn=output_fn,
            model=agent_runtime.model,
            runtime_adapter=agent_runtime.runtime_adapter,
            reasoning_effort=agent_runtime.reasoning_effort,
        )
    except RepoSelectionRejectedError as exc:
        # Preserve legacy behavior: surface validation reject as null with reason so callers'
        # existing `repository is None` branch handles it.
        logger.warning(
            "repo selection: agent returned unknown repository %s, treating as no match",
            exc.returned_repository,
        )
        return RepoSelectionResult(
            repository=None,
            reason=(
                f"Agent selected '{exc.returned_repository}' which is not in the candidate list. "
                f"Original reason: '{exc.reason}'"
            ),
        )
    except RepoSelectionUnavailableError as exc:
        # No picker fallback — collapse operational failure into a null result.
        logger.warning("repo selection unavailable: %s", exc.reason)
        return RepoSelectionResult(repository=None, reason=exc.reason)


async def select_repository_for_report(
    team_id: int,
    user_id: int,
    signals: list[SignalData],
    *,
    signal_report_id: str | None = None,
    sandbox_environment_id: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> RepoSelectionResult:
    """Select the most relevant repository for a set of signals."""
    from products.signals.backend.temporal.types import render_signals_to_text  # noqa: PLC0415

    request_section = render_signals_to_text(signals)
    return await select_repository_for_team(
        team_id,
        user_id,
        request_section,
        step_name="repo_selection",
        signal_report_id=signal_report_id,
        sandbox_environment_id=sandbox_environment_id,
        verbose=verbose,
        output_fn=output_fn,
    )
