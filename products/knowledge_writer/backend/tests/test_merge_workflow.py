import os

import pytest
from unittest.mock import patch

COMMIT_SHA = "b" * 40


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
    "report, expected_status_code, expected_body",
    [
        pytest.param(
            {
                "commit_sha": COMMIT_SHA,
                "commit_url": f"https://github.com/PostHog/posthog/commit/{COMMIT_SHA}",
                "title": "Refactor the query runner",
                "needs_docs": False,
                "reason": "no_mapped_section",
            },
            200,
            {"status": "no_docs"},
            id="verdict",
        ),
        pytest.param(
            {"commit_sha": "not-a-sha", "commit_url": "x", "title": "x", "needs_docs": False, "reason": "x"},
            400,
            None,
            id="invalid",
        ),
    ],
)
def test_merge_verdicts_endpoint_records_a_verdict(
    client, team, user, writer_env, report, expected_status_code, expected_body
) -> None:
    client.force_login(user)

    response = client.post(
        f"/api/projects/{team.id}/knowledge_writer/merge_verdicts/", report, content_type="application/json"
    )

    assert response.status_code == expected_status_code
    if expected_body is not None:
        assert response.json() == expected_body
