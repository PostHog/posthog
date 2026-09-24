"""The GitHub repository a report's signals were filed against.

A GitHub issue is the one inbox source that states its own repository: the issue URL names it.
That is an answer, not a question, so repository selection pins it instead of asking the selection
agent to reason its way back to it. Without the pin the agent weighs the issue against every other
connected repository, and a path or a filename that also exists somewhere else can carry the
implementation — branch, commit, pull request — into a repository the issue never pointed at.

Only a single unambiguous repository counts. A report that merges issues from two repositories
names neither, and guessing between them is the failure this module exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.git import repo_from_github_url

from products.signals.backend.enums import SignalSourceProduct, SignalSourceType

if TYPE_CHECKING:
    # Annotation-only (the module uses postponed evaluation): importing the temporal types at
    # runtime pulls the signals temporal package in, which imports back into report_generation.
    from products.signals.backend.temporal.types import SignalData

__all__ = ["source_repository_from_signals"]


def _issue_repository(signal: SignalData) -> str | None:
    if signal.source_product != SignalSourceProduct.GITHUB or signal.source_type != SignalSourceType.ISSUE:
        return None
    html_url = (signal.extra or {}).get("html_url")
    if not isinstance(html_url, str):
        return None
    repository = repo_from_github_url(html_url)
    return repository.lower() if repository else None


def source_repository_from_signals(signals: list[SignalData]) -> str | None:
    """The one repository these signals come from, lowercased, or None when they name none or many."""
    repositories = {repository for signal in signals if (repository := _issue_repository(signal))}
    return next(iter(repositories)) if len(repositories) == 1 else None
