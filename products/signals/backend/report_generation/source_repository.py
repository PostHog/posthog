"""The GitHub repository a report's signals were filed against.

A GitHub issue is the one inbox source that states its own repository: the issue URL names it.
Repository selection makes it the agent's default (see `select_repo.py`). It is not the answer on
its own, because an issue filed in one repository often asks for a change in another, such as an
SDK, so the agent still checks where the code lives.

Only a single unambiguous repository counts. A report that merges issues from two repositories
names neither, and guessing between them is the failure this module exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from posthog.models.github_integration_base import GitHubIntegrationBase, PullRequestRef

from products.signals.backend.artefact_schemas import SourceIssue
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType

if TYPE_CHECKING:
    from products.signals.backend.temporal.types import SignalData


def _issue_ref(signal: SignalData) -> PullRequestRef | None:
    if signal.source_product != SignalSourceProduct.GITHUB or signal.source_type != SignalSourceType.ISSUE:
        return None
    return GitHubIntegrationBase.parse_issue_url(str((signal.extra or {}).get("html_url") or ""))


def _issue_repository(signal: SignalData) -> str | None:
    ref = _issue_ref(signal)
    return ref.repository.lower() if ref is not None else None


def source_repository_from_signals(signals: list[SignalData]) -> str | None:
    """The one repository these signals come from, lowercased, or None when they name none or many."""
    repositories = {repository for signal in signals if (repository := _issue_repository(signal))}
    return next(iter(repositories)) if len(repositories) == 1 else None


def source_issue_urls(signals: list[SignalData], source_issues: Sequence[SourceIssue]) -> list[str]:
    """The normalized URLs of the GitHub issues a report was filed from, deduplicated, in first-seen order.

    Two records name them: a GitHub issue signal, and the `source_issue` artefact a scout writes when it
    files a report from an issue. Research reads them as the request itself, never as competing work.
    """
    urls = [SourceIssue.github(ref.repository, ref.number).url for signal in signals if (ref := _issue_ref(signal))]
    urls.extend(issue.url for issue in source_issues)
    return list(dict.fromkeys(urls))
