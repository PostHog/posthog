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
    "resolve_team_github_integration",
    "select_repository_for_report",
    "select_repository_for_team",
]


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
