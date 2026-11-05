import dataclasses
from typing import Any

import pytest
from unittest.mock import patch

from products.knowledge_writer.backend.adapters.registry import REGISTRY
from products.knowledge_writer.backend.facade.contracts import (
    AdapterVerdict,
    DocsCommandRequest,
    DocsRequest,
    InvalidAdapterVerdict,
    MergeCheckReport,
)
from products.knowledge_writer.backend.facade.enums import DocsChangeKind, DocsRequestSource
from products.knowledge_writer.backend.logic import intake

SAMPLE_EVENTS: dict[DocsRequestSource, Any] = {
    DocsRequestSource.COMMAND_TAG: DocsCommandRequest(
        repository="PostHog/posthog",
        pull_request_number=123,
        pull_request_url="https://github.com/PostHog/posthog/pull/123",
        head_sha="abc123",
        note="Document the new retention option.",
        requested_by="@octo",
        requested_by_user_id=42,
    ),
    DocsRequestSource.REPO_MERGE: MergeCheckReport(
        commit_sha="a" * 40,
        commit_url=f"https://github.com/PostHog/posthog/commit/{'a' * 40}",
        title="Add a retention option to session replay",
        needs_docs=True,
        reason="mapped_section_changed",
        change_kind=DocsChangeKind.UPDATE,
        page_urls=("https://posthog.com/docs/session-replay/data-retention",),
    ),
}


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


def test_every_registered_adapter_has_a_sample_event() -> None:
    assert set(SAMPLE_EVENTS) == set(REGISTRY)


@pytest.mark.parametrize("source", list(REGISTRY))
def test_adapter_keeps_the_contract(source: DocsRequestSource) -> None:
    adapter = REGISTRY[source]

    verdict = adapter.assess(SAMPLE_EVENTS[source])

    assert adapter.source == source
    assert adapter.instructions.strip()
    assert isinstance(verdict, AdapterVerdict)
    assert verdict.source == source
    assert intake.parse_verdict(verdict) is verdict
    if verdict.request is not None:
        assert verdict.request.dedupe_id.startswith(f"knowledge_writer:{source}:")


def test_docs_requests_for_one_pull_request_share_a_dedupe_id_across_repository_casing() -> None:
    sample = SAMPLE_EVENTS[DocsRequestSource.COMMAND_TAG]
    adapter = REGISTRY[DocsRequestSource.COMMAND_TAG]

    original_casing = adapter.assess(sample)
    lowercase = adapter.assess(dataclasses.replace(sample, repository="posthog/posthog"))

    assert original_casing.request is not None and lowercase.request is not None
    assert original_casing.request.dedupe_id == lowercase.request.dedupe_id


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
        pytest.param(
            dataclasses.asdict(SAMPLE_EVENTS[DocsRequestSource.COMMAND_TAG]), id="raw_event_instead_of_verdict"
        ),
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
