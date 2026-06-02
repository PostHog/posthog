"""Repository selection for Signals reports.

Thin wrapper around `products.tasks.backend.repo_selection.select_repository`.
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

from products.signals.backend.temporal.types import SignalData, render_signals_to_text
from products.tasks.backend.models import Task
from products.tasks.backend.repo_selection import (
    REPO_SELECTION_DUMMY_REPOSITORY,
    RepoSelectionRejectedError,
    RepoSelectionResult,
    RepoSelectionUnavailableError,
    resolve_team_github_integration,
    select_repository,
)

if TYPE_CHECKING:
    from products.tasks.backend.services.custom_prompt_internals import OutputFn

logger = logging.getLogger(__name__)

__all__ = [
    "REPO_SELECTION_DUMMY_REPOSITORY",
    "RepoSelectionRejectedError",
    "RepoSelectionResult",
    "resolve_team_github_integration",
    "select_repository_for_report",
]


async def select_repository_for_report(
    team_id: int,
    user_id: int,
    signals: list[SignalData],
    *,
    sandbox_environment_id: str | None = None,
    verbose: bool = False,
    output_fn: OutputFn = None,
) -> RepoSelectionResult:
    """Select the most relevant repository for a set of signals."""
    context = render_signals_to_text(signals)
    try:
        return await select_repository(
            team_id=team_id,
            user_id=user_id,
            context=context,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            sandbox_environment_id=sandbox_environment_id,
            verbose=verbose,
            output_fn=output_fn,
        )
    except RepoSelectionRejectedError as exc:
        # Preserve legacy behavior: surface validation reject as null with reason so the
        # workflow's existing `repository is None` branch handles it (REQUIRES_HUMAN_INPUT).
        logger.warning(
            "signals repo selection: agent returned unknown repository %s, treating as no match",
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
        # No picker in Signals — collapse operational failure into REQUIRES_HUMAN_INPUT.
        logger.warning("signals repo selection unavailable: %s", exc.reason)
        return RepoSelectionResult(repository=None, reason=exc.reason)
