import dataclasses
from typing import Any

import pytest
from unittest.mock import patch

from products.knowledge_writer.backend.adapters.registry import REGISTRY
from products.knowledge_writer.backend.adapters.repo_merge import RepoMergeAdapter
from products.knowledge_writer.backend.facade.contracts import (
    CriterionResult,
    DocsRequest,
    InvalidAdapterVerdict,
    MergeCheckReport,
)
from products.knowledge_writer.backend.facade.enums import CriterionEffect, DocsChangeKind, DocsRequestSource
from products.knowledge_writer.backend.logic import intake, pull_requests
from products.knowledge_writer.backend.temporal.merge_workflow import MergeCheckInputs

REPORT = MergeCheckReport(
    commit_sha="a" * 40,
    commit_url=f"https://github.com/PostHog/posthog/commit/{'a' * 40}",
    title="Add a retention option to session replay",
    needs_docs=True,
    reason="mapped_section_changed",
    repository="PostHog/posthog",
    pull_request_number=7,
    low_confidence=True,
    criteria=(
        CriterionResult(
            criterion="release_state",
            value="ga",
            source="model:claude-sonnet-5-5",
            evidence="Ships to everyone",
            effect=CriterionEffect.SUPPORTS,
        ),
    ),
    change_kind=DocsChangeKind.UPDATE,
    page_urls=("https://posthog.com/docs/session-replay/data-retention",),
)


def _inputs(origin: DocsRequestSource, repository: str = REPORT.repository) -> MergeCheckInputs:
    return MergeCheckInputs(
        commit_sha=REPORT.commit_sha,
        team_id=1,
        repository=repository,
        pull_request_number=REPORT.pull_request_number,
        origin=origin,
        requested_by="@octo",
        requested_by_user_id=42,
        note="Document the new retention option.",
    )


def _valid_request(**overrides: Any) -> dict[str, Any]:
    return {
        "source": "command_tag",
        "source_url": "https://github.com/PostHog/posthog/pull/123",
        "evidence": "Pull request 123.",
        "change_kind": "update",
        "suggested_page_urls": [],
        "trigger_instructions": "",
        "dedupe_id": "knowledge_writer:command_tag:PostHog.posthog#123",
        **overrides,
    }


def _valid_verdict(**overrides: Any) -> dict[str, Any]:
    return {
        "source": "command_tag",
        "subject_id": "PostHog.posthog#123",
        "needs_docs": True,
        "reason": "requested",
        "request": _valid_request(),
        **overrides,
    }


@pytest.mark.parametrize("origin", list(DocsRequestSource))
def test_every_input_gets_its_verdict_from_the_shared_builder(origin: DocsRequestSource) -> None:
    adapter = REGISTRY[origin]

    verdict = RepoMergeAdapter().assess(REPORT, _inputs(origin))

    assert adapter.source == origin
    assert adapter.instructions.strip()
    assert verdict.source == origin
    assert intake.parse_verdict(verdict) is verdict
    assert verdict.request is not None
    assert (verdict.request.trigger_instructions, verdict.request.requested_by_user_id) == (
        "Document the new retention option.",
        42,
    )


def test_a_merge_and_a_docs_command_on_one_pull_request_share_a_dedupe_id_across_repository_casing() -> None:
    merge = RepoMergeAdapter().assess(REPORT, _inputs(DocsRequestSource.REPO_MERGE))
    command = RepoMergeAdapter().assess(
        dataclasses.replace(REPORT, repository="posthog/posthog"),
        _inputs(DocsRequestSource.COMMAND_TAG, repository="posthog/posthog"),
    )

    assert merge.request is not None and command.request is not None
    assert merge.request.dedupe_id == command.request.dedupe_id


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("not a verdict", id="string"),
        pytest.param({**_valid_verdict(), "extra": 1}, id="extra_field"),
        pytest.param(_valid_verdict(request=None), id="needs_docs_without_request"),
        pytest.param(_valid_verdict(needs_docs=False), id="request_without_needs_docs"),
        pytest.param(_valid_verdict(source="repo_merge"), id="request_from_another_source"),
        pytest.param(_valid_verdict(request=_valid_request(dedupe_id="anything")), id="bad_dedupe_id"),
        pytest.param(_valid_verdict(request=_valid_request(change_kind="rewrite")), id="unknown_change_kind"),
        pytest.param(dataclasses.asdict(REPORT), id="raw_report_instead_of_verdict"),
    ],
)
def test_intake_rejects_anything_but_a_valid_verdict(payload: object) -> None:
    with patch.object(intake, "capture_verdict") as capture_verdict, pytest.raises(InvalidAdapterVerdict):
        intake.submit(payload, team_id=1)

    capture_verdict.assert_not_called()


def test_intake_accepts_a_valid_verdict_as_plain_data() -> None:
    verdict = intake.parse_verdict(_valid_verdict())

    assert verdict.request == DocsRequest(
        source=DocsRequestSource.COMMAND_TAG,
        source_url="https://github.com/PostHog/posthog/pull/123",
        evidence="Pull request 123.",
        change_kind=DocsChangeKind.UPDATE,
        suggested_page_urls=(),
        trigger_instructions="",
        dedupe_id="knowledge_writer:command_tag:PostHog.posthog#123",
    )


def test_repo_merge_verdict_event_records_repository_pull_request_and_criteria() -> None:
    verdict = RepoMergeAdapter().assess(REPORT, _inputs(DocsRequestSource.REPO_MERGE))

    with patch.object(pull_requests, "ph_scoped_capture") as scoped_capture:
        for check_id in ("first-check-run", "second-check-run"):
            intake.capture_verdict(dataclasses.replace(verdict, check_id=check_id), team_id=1)

    capture_calls = scoped_capture.return_value.__enter__.return_value.call_args_list
    assert capture_calls[0].kwargs["uuid"] != capture_calls[1].kwargs["uuid"]
    properties = capture_calls[-1].kwargs["properties"]
    assert properties["repository"] == "PostHog/posthog"
    assert properties["pull_request_number"] == 7
    assert properties["low_confidence"] is True
    assert properties["change_kind"] == "update"
    assert properties["criteria"] == [
        {
            "criterion": "release_state",
            "value": "ga",
            "source": "model:claude-sonnet-5-5",
            "evidence": "Ships to everyone",
            "effect": "supports",
        }
    ]
