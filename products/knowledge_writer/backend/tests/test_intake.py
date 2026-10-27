import os
import dataclasses

import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration

from products.knowledge_writer.backend.adapters import REGISTRY
from products.knowledge_writer.backend.facade.contracts import DocsCommandRequest
from products.knowledge_writer.backend.facade.enums import DocsRequestSource
from products.knowledge_writer.backend.logic import caps, intake
from products.knowledge_writer.backend.logic.pull_requests import LINK_BACK_START
from products.knowledge_writer.backend.logic.records import PULL_REQUEST_STATE_KEY, REQUEST_STATE_KEY
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import TaskRun

FLAG_CHECK = "products.knowledge_writer.backend.feature_flags.posthoganalytics.feature_enabled"
GITHUB = "posthog.models.integration.GitHubIntegration"
CREATE_PULL_REQUEST = f"{GITHUB}.create_pull_request"
LIST_PULL_REQUESTS = f"{GITHUB}.api_request"
CAPTURE_ALERT = "products.knowledge_writer.backend.logic.caps.capture_exception"
DOCS_HEAD = {"repository": "PostHog/posthog.com", "branch": "docs/retention"}
SECTION_PAGE = "https://posthog.com/docs/session-replay/retention"
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
    Integration.objects.create(
        team=team, kind="github", integration_id="31337", config={"account": {"name": "PostHog"}}
    )
    with patch.dict(
        os.environ,
        {
            "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
            "KNOWLEDGE_WRITER_USER_ID": str(user.id),
            "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
        },
    ):
        yield


def _open_on_github(*bodies_by_number: tuple[int, str]) -> MagicMock:
    listed = [
        {
            "number": number,
            "html_url": f"https://github.com/PostHog/posthog.com/pull/{number}",
            "body": body,
            "head": {"ref": DOCS_HEAD["branch"], "repo": {"full_name": "PostHog/posthog.com"}},
        }
        for number, body in bodies_by_number
    ]
    return MagicMock(status_code=200, json=MagicMock(return_value=listed))


def _verdict(pull_request_number: int = 123, suggested_page_urls: tuple[str, ...] = ()):
    verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(
        dataclasses.replace(
            COMMAND,
            pull_request_number=pull_request_number,
            pull_request_url=f"https://github.com/PostHog/posthog/pull/{pull_request_number}",
        )
    )
    assert verdict.request is not None
    return dataclasses.replace(
        verdict, request=dataclasses.replace(verdict.request, suggested_page_urls=suggested_page_urls)
    )


def _finish_run(task_id, django_capture_on_commit_callbacks) -> None:
    run = TaskRun.objects.get(task_id=task_id)
    with django_capture_on_commit_callbacks(execute=True):
        run.status = TaskRun.Status.COMPLETED
        run.output = {"head_branches": [DOCS_HEAD]}
        run.save(update_fields=["status", "output"])


@pytest.mark.django_db
def test_no_agent_starts_without_settings(team) -> None:
    with patch(START_WORKFLOW) as start_workflow:
        outcome = intake.submit(_verdict(), team_id=team.id)

    assert outcome.status == "unconfigured"
    start_workflow.assert_not_called()


@pytest.mark.django_db
def test_no_agent_starts_while_the_launch_flag_is_off(team, writer_env) -> None:
    with (
        patch(FLAG_CHECK, return_value=False),
        patch(LIST_PULL_REQUESTS, return_value=_open_on_github()),
        patch(START_WORKFLOW) as start_workflow,
    ):
        outcome = intake.submit(_verdict(), team_id=team.id)

    assert outcome.status == "shadow"
    start_workflow.assert_not_called()


@pytest.mark.django_db
def test_a_request_starts_one_internal_writer_task_and_a_repeat_is_a_duplicate(team, user, writer_env) -> None:
    verdict = _verdict()
    assert verdict.request is not None

    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, return_value=_open_on_github()),
        patch(START_WORKFLOW),
    ):
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


@pytest.mark.django_db
def test_a_finished_writer_run_opens_one_linked_docs_pull_request_and_a_same_section_request_joins_it(
    team, writer_env, django_capture_on_commit_callbacks
) -> None:
    opened = {"success": True, "pr_url": "https://github.com/PostHog/posthog.com/pull/9", "pr_number": 9}
    first_verdict = _verdict(suggested_page_urls=(SECTION_PAGE,))
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, return_value=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(first_verdict, team_id=team.id)
    assert started.task_id is not None
    with patch(CREATE_PULL_REQUEST, return_value=opened) as create_pull_request:
        _finish_run(started.task_id, django_capture_on_commit_callbacks)
        with django_capture_on_commit_callbacks(execute=True):
            TaskRun.objects.get(task_id=started.task_id).save(update_fields=["output"])

    create_pull_request.assert_called_once()
    assert create_pull_request.call_args.args == ("posthog.com",)
    assert create_pull_request.call_args.kwargs["head_branch"] == DOCS_HEAD["branch"]
    assert LINK_BACK_START in create_pull_request.call_args.kwargs["body"]
    assert COMMAND.pull_request_url in create_pull_request.call_args.kwargs["body"]

    first_body = create_pull_request.call_args.kwargs["body"]
    second_verdict = _verdict(pull_request_number=456, suggested_page_urls=(SECTION_PAGE,))
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, return_value=_open_on_github((9, first_body))),
        patch(START_WORKFLOW),
    ):
        joined = intake.submit(second_verdict, team_id=team.id)
    assert joined.status == "joined"
    assert joined.task_id is not None
    assert joined.pull_request_url == opened["pr_url"]
    assert TaskRun.objects.get(task_id=joined.task_id).branch == DOCS_HEAD["branch"]

    with (
        patch(f"{GITHUB}.get_pull_request", return_value={"success": True, "state": "open", "body": first_body}),
        patch(f"{GITHUB}.update_pull_request_body", return_value={"success": True}) as update_body,
        patch(CREATE_PULL_REQUEST) as second_create,
    ):
        _finish_run(joined.task_id, django_capture_on_commit_callbacks)

    second_create.assert_not_called()
    updated_body = update_body.call_args.args[2]
    assert COMMAND.pull_request_url in updated_body
    assert "https://github.com/PostHog/posthog/pull/456" in updated_body
    stored = tasks_facade.read_task_state_entry(joined.task_id, team.id, PULL_REQUEST_STATE_KEY)
    assert isinstance(stored, dict)
    assert stored["number"] == 9


@pytest.mark.django_db
@pytest.mark.parametrize("cap", ["daily_run", "open_pull_request"])
def test_no_agent_starts_past_a_cap_and_the_cap_raises_an_alert(team, writer_env, cap, monkeypatch) -> None:
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, return_value=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        intake.submit(_verdict(), team_id=team.id)
    monkeypatch.setattr(caps, "DAILY_RUN_CAP", 1 if cap == "daily_run" else 60)
    monkeypatch.setattr(intake, "OPEN_PULL_REQUEST_CAP", 0 if cap == "open_pull_request" else 10)

    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, return_value=_open_on_github()),
        patch(START_WORKFLOW) as start_workflow,
        patch(CAPTURE_ALERT) as capture_alert,
    ):
        outcome = intake.submit(_verdict(pull_request_number=456), team_id=team.id)

    assert outcome.status == "capped"
    start_workflow.assert_not_called()
    assert capture_alert.call_args.kwargs["additional_properties"]["cap"] == cap
