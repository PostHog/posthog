from datetime import UTC, datetime

import pytest
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync

from products.signals.backend.agent_runtime import DEFAULT_RUNTIME
from products.signals.backend.artefact_schemas import SourceIssue
from products.signals.backend.report_generation import select_repo
from products.signals.backend.report_generation.source_repository import (
    source_issue_urls,
    source_repository_from_signals,
)
from products.signals.backend.temporal.types import SignalData
from products.tasks.backend.facade.repo_selection_types import RepoSelectionResult

ISSUE_URL = "https://github.com/PostHog/posthog/issues/105295"


def _signal(
    *,
    source_product: str = "github",
    source_type: str = "issue",
    extra: dict | None = None,
) -> SignalData:
    return SignalData(
        signal_id="s1",
        content="Something is broken",
        source_product=source_product,
        source_type=source_type,
        source_id="1",
        weight=1.0,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        extra={"html_url": ISSUE_URL} if extra is None else extra,
    )


@pytest.mark.parametrize(
    "signals,expected",
    [
        ([_signal()], "posthog/posthog"),
        ([_signal(), _signal(extra={"html_url": "https://github.com/PostHog/posthog/issues/999"})], "posthog/posthog"),
        # Two repositories name neither: picking between them is the wrong-repo failure itself.
        ([_signal(), _signal(extra={"html_url": "https://github.com/posthog/posthog-js/issues/1"})], None),
        # A support ticket that quotes an issue link does not make that repository its source.
        ([_signal(source_product="zendesk", source_type="ticket")], None),
        ([_signal(extra={})], None),
        ([_signal(extra={"html_url": "https://github.com.evil.tld/posthog/posthog/issues/1"})], None),
        ([_signal(extra={"html_url": 42})], None),
        ([], None),
    ],
)
def test_source_repository_from_signals(signals: list[SignalData], expected: str | None) -> None:
    assert source_repository_from_signals(signals) == expected


SCOUT_ISSUE = SourceIssue.github("PostHog/posthog-js", 12)


@pytest.mark.parametrize(
    "signals,source_issues,expected",
    [
        ([_signal()], [], ["https://github.com/posthog/posthog/issues/105295"]),
        # A scout files its report with no GitHub issue signal, so only the artefact names the issue.
        ([], [SCOUT_ISSUE], ["https://github.com/posthog/posthog-js/issues/12"]),
        (
            [_signal(), _signal(extra={"html_url": "https://github.com/posthog/posthog/issues/105295"})],
            [SCOUT_ISSUE, SourceIssue.github("posthog/posthog", 105295)],
            ["https://github.com/posthog/posthog/issues/105295", "https://github.com/posthog/posthog-js/issues/12"],
        ),
        # A ticket from another source that quotes an issue link does not exempt that issue.
        ([_signal(source_product="zendesk", source_type="ticket")], [], []),
        ([_signal(extra={"html_url": "https://github.com.evil.tld/posthog/posthog/issues/1"})], [], []),
        ([_signal(extra={"html_url": "https://github.com/posthog/posthog/pull/1"})], [], []),
        ([], [], []),
    ],
)
def test_source_issue_urls(signals: list[SignalData], source_issues: list[SourceIssue], expected: list[str]) -> None:
    assert source_issue_urls(signals, source_issues) == expected


class TestSelectRepositoryDefaultsToTheSourceRepository(BaseTest):
    def test_report_selection_passes_the_repository_its_issue_was_filed_against(self):
        select = AsyncMock(return_value=RepoSelectionResult(repository="posthog/posthog", reason="selected"))
        with (
            patch.object(select_repo, "select_repository", new=select),
            patch.object(select_repo, "resolve_agent_runtime", return_value=DEFAULT_RUNTIME),
            patch.object(select_repo, "wrong_repo_corrections_block", return_value=None),
        ):
            async_to_sync(select_repo.select_repository_for_report)(self.team.id, self.user.id, [_signal()])

        assert select.await_args is not None
        assert select.await_args.kwargs["source_repository"] == "posthog/posthog"
