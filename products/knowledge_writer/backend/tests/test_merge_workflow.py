import os

import pytest
from unittest.mock import patch

COMMIT_SHA = "b" * 40
START_MERGE_CHECK = "products.knowledge_writer.backend.temporal.client.start_merge_check"


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
    start_merge_check.assert_called_once_with(COMMIT_SHA, team_id=team.id)
