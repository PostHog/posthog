"""The GitHub repository a report's signals were filed against.

A GitHub issue is the one inbox source that states its own repository: the issue URL names it.
Repository selection makes it the agent's default (see `select_repo.py`). It is not the answer on
its own, because an issue filed in one repository often asks for a change in another, such as an
SDK, so the agent still checks where the code lives.

Only a single unambiguous repository counts. A report that merges issues from two repositories
names neither, and guessing between them is the failure this module exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.models.github_integration_base import GitHubIntegrationBase

from products.signals.backend.enums import SignalSourceProduct, SignalSourceType

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData


def _issue_repository(signal: SignalData) -> str | None:
    if signal.source_product != SignalSourceProduct.GITHUB or signal.source_type != SignalSourceType.ISSUE:
        return None
    ref = GitHubIntegrationBase.parse_issue_url(str((signal.extra or {}).get("html_url") or ""))
    return ref.repository.lower() if ref is not None else None


def source_repository_from_signals(signals: list[SignalData]) -> str | None:
    """The one repository these signals come from, lowercased, or None when they name none or many."""
    repositories = {repository for signal in signals if (repository := _issue_repository(signal))}
    return next(iter(repositories)) if len(repositories) == 1 else None
