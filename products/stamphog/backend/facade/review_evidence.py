"""Registry of external reviewers that can tell stamphog where their review of a PR head stands.

A product that reviews pull requests registers a provider from its ``AppConfig.ready()``. Stamphog
cannot import such a product when that product already depends on stamphog, so the provider comes
to stamphog through this registry. Stamphog's review workflow asks every registered provider. A
pending review keeps stamphog waiting, and a completed review of the current head and merge base
counts as assurance only when it skipped no file. A provider that raises adds nothing, except that
a review it reported as pending earlier in the run stays pending. With no provider stamphog
reviews as before. Mirrors ``inbox_hooks.py``.

Keep this module light. ``AppConfig.ready()`` imports it on the django.setup() path, so it must
never import Django models or heavy product internals.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class ReviewEvidenceState(StrEnum):
    # Accepted but not started, or running. A review stays pending until its findings are on the PR.
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, kw_only=True)
class ReviewEvidence:
    """Where one external review of one PR head stands."""

    state: ReviewEvidenceState
    # The reviewer's name as people see it on the PR.
    reviewer: str
    # The review depth as people see it. Empty when the reviewer does not know it yet.
    review_kind: str
    # Valid findings of a completed review. Zero while pending or failed.
    findings_count: int
    # True when the review posted on the PR. A clean review can post nothing, so it stays False.
    published: bool
    head_sha: str
    # The base branch the review took the diff against, for people to read.
    base_ref: str = ""
    # The merge base the review took the diff against. A retarget or a base merge into the head
    # changes the diff, so a review with another or an empty merge base does not count.
    base_sha: str = ""
    # The changed files the review left out. It is no assurance for those files.
    skipped_paths: tuple[str, ...] = ()


# (repository "owner/name", pr_number, head_sha) -> the evidence for exactly that head, or None
# when the reviewer knows no review of that head.
ReviewEvidenceProvider = Callable[[str, int, str], ReviewEvidence | None]

_review_evidence_providers: list[ReviewEvidenceProvider] = []


def register_review_evidence_provider(fn: ReviewEvidenceProvider) -> None:
    # AppConfig.ready() can run more than once in one process, for example in tests.
    if fn not in _review_evidence_providers:
        _review_evidence_providers.append(fn)


def get_review_evidence_providers() -> tuple[ReviewEvidenceProvider, ...]:
    return tuple(_review_evidence_providers)
