import os

import pytest
from unittest.mock import patch

from posthog.models.integration import Integration

from products.knowledge_writer.backend.adapters.registry import REGISTRY
from products.knowledge_writer.backend.facade.contracts import DocsCommandRequest
from products.knowledge_writer.backend.facade.enums import DocsRequestSource
from products.knowledge_writer.backend.logic import intake
from products.knowledge_writer.backend.logic.launch import REQUEST_STATE_KEY
from products.tasks.backend.facade import api as tasks_facade

FLAG_CHECK = "products.knowledge_writer.backend.feature_flags.posthoganalytics.feature_enabled"
START_WORKFLOW = "products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow"

COMMAND = DocsCommandRequest(
    repository="PostHog/posthog",
    pull_request_number=123,
    pull_request_url="https://github.com/PostHog/posthog/pull/123",
    head_sha="abc123",
    note="Document the new retention option.",
    requested_by="@octo",
)


@pytest.fixture
def writer_env(team, user):
    Integration.objects.create(team=team, kind="github", integration_id="31337", config={})
    with patch.dict(
        os.environ,
        {
            "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
            "KNOWLEDGE_WRITER_USER_ID": str(user.id),
            "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
        },
    ):
        yield


def _verdict():
    return REGISTRY[DocsRequestSource.COMMAND_TAG].assess(COMMAND)


@pytest.mark.django_db
def test_no_agent_starts_without_settings(team) -> None:
    with patch(START_WORKFLOW) as start_workflow:
        outcome = intake.submit(_verdict(), team_id=team.id)

    assert outcome.status == "unconfigured"
    start_workflow.assert_not_called()


@pytest.mark.django_db
def test_no_agent_starts_while_the_launch_flag_is_off(team, writer_env) -> None:
    with patch(FLAG_CHECK, return_value=False), patch(START_WORKFLOW) as start_workflow:
        outcome = intake.submit(_verdict(), team_id=team.id)

    assert outcome.status == "shadow"
    start_workflow.assert_not_called()


@pytest.mark.django_db
def test_a_request_starts_one_internal_writer_task_and_a_repeat_is_a_duplicate(team, user, writer_env) -> None:
    verdict = _verdict()
    assert verdict.request is not None

    with patch(FLAG_CHECK, return_value=True), patch(START_WORKFLOW):
        started = intake.submit(verdict, team_id=team.id)
        repeated = intake.submit(verdict, team_id=team.id)

    assert started.status == "started"
    assert repeated.status == "duplicate"
    assert repeated.task_id == started.task_id
    task = tasks_facade.get_task_by_origin_key(team.id, verdict.request.dedupe_id)
    assert task is not None
    assert task.origin_product == tasks_facade.TaskOriginProduct.KNOWLEDGE_WRITER
    assert task.repository == "posthog/posthog.com"
    stored_request = tasks_facade.read_task_state_entry(task.id, team.id, REQUEST_STATE_KEY)
    assert isinstance(stored_request, dict)
    assert stored_request["dedupe_id"] == verdict.request.dedupe_id
