import os

import pytest
from unittest.mock import patch

from products.business_knowledge.backend.facade.contracts import KnowledgeHit
from products.knowledge_writer.backend.facade.enums import DocsChangeKind, DocsRequestSource
from products.knowledge_writer.backend.temporal.merge_workflow import MergeCheckCommand, MergeCheckInputs, check_merge
from products.knowledge_writer.merge_check.judge import JudgeVerdict
from products.knowledge_writer.merge_check.tests.test_merge_check import FakePostHogGitHub, judge_recording

COMMIT_SHA = "b" * 40
START_MERGE_CHECK = "products.knowledge_writer.backend.temporal.client.start_merge_check"
MERGE_WORKFLOW = "products.knowledge_writer.backend.temporal.merge_workflow"
RETENTION_PAGE = "https://posthog.com/docs/session-replay/data-retention"


@pytest.fixture
def writer_env(team, user):
    with patch.dict(
        os.environ,
        {
            "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
            "KNOWLEDGE_WRITER_USER_ID": str(user.id),
            "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
        },
    ):
        yield


@pytest.mark.django_db
@pytest.mark.parametrize(
    "commit_sha, expected_status_code",
    [
        pytest.param(COMMIT_SHA, 202, id="merge"),
        pytest.param("not-a-sha", 400, id="invalid"),
    ],
)
def test_merge_pushes_endpoint_starts_the_merge_check(
    client, team, user, writer_env, commit_sha, expected_status_code
) -> None:
    client.force_login(user)

    with patch(START_MERGE_CHECK) as start_merge_check:
        response = client.post(
            f"/api/projects/{team.id}/knowledge_writer/merge_pushes/",
            {"commit_sha": commit_sha},
            content_type="application/json",
        )

    assert response.status_code == expected_status_code
    if expected_status_code != 202:
        start_merge_check.assert_not_called()
        return
    start_merge_check.assert_called_once_with(MergeCheckInputs(commit_sha=COMMIT_SHA, team_id=team.id))


@pytest.mark.parametrize(
    "needs_docs, expected_page_urls",
    [
        pytest.param(True, (RETENTION_PAGE,), id="judged_yes"),
        pytest.param(False, None, id="judged_no"),
    ],
)
def test_a_docs_command_goes_through_the_judge_and_takes_its_pages_from_business_knowledge(
    needs_docs, expected_page_urls
) -> None:
    inputs = MergeCheckInputs(
        commit_sha=None,
        team_id=1,
        repository="PostHog/posthog-js",
        command=MergeCheckCommand(
            pull_request_number=7,
            pull_request_url="https://github.com/PostHog/posthog-js/pull/7",
            head_sha="abc123",
            note="Mention the retention option.",
            requested_by="@octo",
            requested_by_user_id=42,
        ),
    )
    verdict = JudgeVerdict(
        needs_docs=needs_docs,
        change_kind=DocsChangeKind.UPDATE if needs_docs else None,
        docs_query="session replay retention",
        reason="new option",
    )
    hits = [
        KnowledgeHit(document_title="Retention", heading_path="", url=url, content="")
        for url in (RETENTION_PAGE, "https://posthog.com/blog/retention")
    ]
    github = FakePostHogGitHub(COMMIT_SHA)

    with (
        patch(f"{MERGE_WORKFLOW}.docs_github", return_value=github),
        patch(f"{MERGE_WORKFLOW}.judge_client", return_value=judge_recording(verdict, [])),
        patch(f"{MERGE_WORKFLOW}.business_knowledge_facade.search_knowledge", return_value=hits),
        patch(f"{MERGE_WORKFLOW}.intake.submit") as submit,
    ):
        check_merge(inputs, is_final_attempt=True)

    (submitted,) = submit.call_args.args
    assert github.requested_paths[0] == "/repos/PostHog/posthog-js/pulls/7"
    assert (
        submitted.source,
        submitted.subject_id,
        submitted.needs_docs,
        submitted.requested_by,
        submitted.requested_by_user_id,
    ) == (DocsRequestSource.COMMAND_TAG, "posthog.posthog-js#7", needs_docs, "@octo", 42)
    assert (submitted.request.suggested_page_urls if submitted.request else None) == expected_page_urls
