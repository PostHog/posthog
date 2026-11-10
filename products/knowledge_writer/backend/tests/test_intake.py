import os
import dataclasses
from collections.abc import Callable

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.instance_setting import override_instance_config
from posthog.models.integration import Integration

from products.knowledge_writer.backend.adapters.registry import REGISTRY
from products.knowledge_writer.backend.facade.contracts import DocsCommandRequest
from products.knowledge_writer.backend.facade.enums import DocsRequestSource
from products.knowledge_writer.backend.feature_flags import AGENT_LAUNCH_FLAG
from products.knowledge_writer.backend.logic import caps, intake
from products.knowledge_writer.backend.logic.launch import WRITER_IDLE_TIMEOUT_SECONDS
from products.knowledge_writer.backend.logic.pull_requests import (
    COMPARE_FILE_LIMIT,
    LINK_BACK_START,
    open_or_join_pull_request,
    section_label,
    section_marker,
    settle_publication,
)
from products.knowledge_writer.backend.logic.records import (
    HEAD_BRANCH_STATE_KEY,
    JOIN_STATE_KEY,
    PUBLICATION_CLAIM_STATE_KEY,
    PUBLICATION_LEASE,
    PULL_REQUEST_FAILURE_STATE_KEY,
    PULL_REQUEST_STATE_KEY,
    REQUEST_STATE_KEY,
    publication_claim,
)
from products.knowledge_writer.backend.logic.routing import docs_section
from products.knowledge_writer.backend.settings import writer_settings
from products.knowledge_writer.backend.task_profiles import WRITER
from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.models import Task, TaskRun

FLAG_CHECK = "products.knowledge_writer.backend.feature_flags.posthoganalytics.feature_enabled"
GITHUB = "posthog.models.integration.GitHubIntegration"
CREATE_PULL_REQUEST = f"{GITHUB}.create_pull_request"
LIST_PULL_REQUESTS = f"{GITHUB}.api_request"
CAPTURE_ALERT = "products.knowledge_writer.backend.logic.caps.capture_exception"
DOCS_HEAD = {"repository": "PostHog/posthog.com", "branch": "docs/retention"}
SECTION_PAGE = "https://posthog.com/docs/session-replay/retention"
DOCS_PAGE_PATH = "contents/docs/session-replay/retention.mdx"
WORKFLOW_PATH = ".github/workflows/deploy.yml"
SIBLING_OF_DOCS_PATH = "contents/docs-tools/build.js"
REPOSITORY_SOURCED_PAGE = "https://posthog.com/docs/logs/logql-api"
START_WORKFLOW = "products.tasks.backend.logic.services.workflow_dispatch.enqueue_or_start_workflow"
WRITER_APP_LOGIN = "posthog-app[bot]"
CAPTURE_VERDICT = "products.knowledge_writer.backend.logic.intake.capture_verdict"
KNOWLEDGE_WRITER_ENABLED = "products.knowledge_writer.backend.settings.is_writer_enabled"
START_PUBLISH = "products.knowledge_writer.backend.temporal.client.start_publish"

COMMAND = DocsCommandRequest(
    repository="PostHog/posthog",
    pull_request_number=123,
    pull_request_url="https://github.com/PostHog/posthog/pull/123",
    head_sha="abc123",
    note="Document the new retention option.",
    requested_by="@octo",
    requested_by_user_id=42,
)


@pytest.fixture
def writer_env(team, user):
    Integration.objects.create(
        team=team, kind="github", integration_id="31337", config={"account": {"name": "PostHog"}}
    )
    with (
        override_instance_config("GITHUB_APP_SLUG", "posthog-app"),
        patch.dict(
            os.environ,
            {
                "KNOWLEDGE_WRITER_TEAM_ID": str(team.id),
                "KNOWLEDGE_WRITER_USER_ID": str(user.id),
                "KNOWLEDGE_WRITER_DOCS_REPOSITORY": "PostHog/posthog.com",
            },
        ),
        patch(f"{GITHUB}.get_default_branch", return_value="master"),
        patch(LIST_PULL_REQUESTS, side_effect=_changed_on_branch(DOCS_PAGE_PATH)),
    ):
        yield


def _open_on_github(
    *bodies_by_number: tuple[int, str],
    author_login: str = WRITER_APP_LOGIN,
    published_page_paths: tuple[str, ...] = (),
    lookup_error: Exception | None = None,
    labels: tuple[str, ...] = (),
) -> Callable[..., MagicMock]:
    listed = [
        {
            "number": number,
            "html_url": f"https://github.com/PostHog/posthog.com/pull/{number}",
            "body": body,
            "user": {"login": author_login},
            "labels": [{"name": label} for label in labels],
            "head": {"ref": DOCS_HEAD["branch"], "repo": {"full_name": "PostHog/posthog.com"}},
        }
        for number, body in bodies_by_number
    ]

    def respond(method: str, path: str, **kwargs: object) -> MagicMock:
        if "/compare/" in path:
            return _changed_on_branch(DOCS_PAGE_PATH)(method, path)
        if "/contents/docs/published/docs/" in path:
            if lookup_error is not None:
                raise lookup_error
            is_published = any(f"/docs/published/docs/{page_path}." in path for page_path in published_page_paths)
            return MagicMock(status_code=200 if is_published else 404)
        return MagicMock(status_code=200, json=MagicMock(return_value=listed))

    return respond


def _changed_on_branch(*changed_files: str | dict[str, str], status_code: int = 200) -> Callable[..., MagicMock]:
    listed = [changed if isinstance(changed, dict) else {"filename": changed} for changed in changed_files]
    compared = {"ahead_by": 1, "files": listed}
    return lambda method, path, **kwargs: MagicMock(status_code=status_code, json=MagicMock(return_value=compared))


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


def _run_publish_workflow_inline(task_run_id, *, team_id: int) -> None:
    try:
        open_or_join_pull_request(task_run_id, team_id=team_id)
    except Exception:
        settle_publication(task_run_id, team_id=team_id, has_failed=True)
        return
    settle_publication(task_run_id, team_id=team_id, has_failed=False)


def _issued_branch(task_id) -> str:
    issued = (Task.objects.get(id=task_id).state or {}).get(HEAD_BRANCH_STATE_KEY)
    assert isinstance(issued, str)
    return issued


def _finish_run(
    task_id,
    django_capture_on_commit_callbacks,
    *,
    pushed_branches: tuple[str, ...] | None = None,
    changed_files: tuple[str | dict[str, str], ...] = (DOCS_PAGE_PATH,),
    compare_status_code: int = 200,
) -> list[str]:
    run = TaskRun.objects.get(task_id=task_id)
    branches = pushed_branches or (_issued_branch(task_id),)
    compared = _changed_on_branch(*changed_files, status_code=compare_status_code)
    with (
        patch(LIST_PULL_REQUESTS, side_effect=compared) as github_request,
        django_capture_on_commit_callbacks(execute=True),
    ):
        run.status = TaskRun.Status.COMPLETED
        run.output = {"head_branches": [{"repository": DOCS_HEAD["repository"], "branch": b} for b in branches]}
        run.save(update_fields=["status", "output"])
    return [call.args[1] for call in github_request.call_args_list]


@pytest.mark.django_db
def test_a_writer_run_with_malformed_output_still_saves_completed(team, writer_env) -> None:
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(_verdict(), team_id=team.id)
    assert started.task_id is not None
    run = TaskRun.objects.get(task_id=started.task_id)
    run.status = TaskRun.Status.COMPLETED
    run.output = "not a dict"

    run.save(update_fields=["status", "output"])

    assert TaskRun.objects.get(id=run.id).status == TaskRun.Status.COMPLETED


@pytest.mark.django_db
@pytest.mark.parametrize("has_writer_settings", [False, True])
def test_nothing_runs_or_is_captured_while_the_writer_is_unconfigured_or_flagged_off(
    request, team, has_writer_settings: bool
) -> None:
    if has_writer_settings:
        request.getfixturevalue("writer_env")
    with (
        patch(FLAG_CHECK, return_value=False),
        patch(CAPTURE_VERDICT) as capture_verdict,
        patch(START_WORKFLOW) as start_workflow,
    ):
        outcome = intake.submit(_verdict(), team_id=team.id)

    assert outcome.status == "unconfigured"
    capture_verdict.assert_not_called()
    start_workflow.assert_not_called()


@pytest.mark.django_db
def test_no_agent_starts_while_the_launch_flag_is_off(team, writer_env) -> None:
    with (
        patch(FLAG_CHECK, side_effect=lambda flag, *args, **kwargs: flag != AGENT_LAUNCH_FLAG),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
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
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
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
    assert Task.objects.get(id=task.id).profile == WRITER.key
    assert task.repository == "posthog/posthog.com"
    stored_request = tasks_facade.read_task_state_entry(task.id, team.id, REQUEST_STATE_KEY)
    assert isinstance(stored_request, dict)
    assert stored_request["dedupe_id"] == verdict.request.dedupe_id
    Task.objects.get(id=task.id).create_run()
    run_states = TaskRun.objects.filter(task_id=task.id).values_list("state", flat=True)
    assert len(run_states) == 2
    assert all(state["config_snapshot"]["connectors"]["mcp_installation_ids"] == [] for state in run_states)
    assert all(state["include_live_context"] is False for state in run_states)
    assert "push" in [state.get("github_token_scope") for state in run_states]


@pytest.mark.django_db
def test_a_finished_writer_run_opens_one_linked_docs_pull_request_and_a_same_section_request_waits_then_joins_it(
    team, writer_env, django_capture_on_commit_callbacks, monkeypatch
) -> None:
    monkeypatch.setattr(KNOWLEDGE_WRITER_ENABLED, lambda team_id: True)
    monkeypatch.setattr(START_PUBLISH, _run_publish_workflow_inline)
    monkeypatch.setenv("KNOWLEDGE_WRITER_DOCS_PATHS", "contents/docs")
    opened = {"success": True, "pr_url": "https://github.com/PostHog/posthog.com/pull/9", "pr_number": 9}
    first_verdict = _verdict(suggested_page_urls=(SECTION_PAGE,))
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(first_verdict, team_id=team.id)
    assert started.task_id is not None
    second_verdict = _verdict(pull_request_number=456, suggested_page_urls=(SECTION_PAGE,))
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW) as start_workflow,
    ):
        busy = intake.submit(second_verdict, team_id=team.id)
    assert busy.status == "section_busy"
    start_workflow.assert_not_called()
    issued_branch = _issued_branch(started.task_id)
    for pushed_branches in (("docs/another-branch",), (issued_branch, "docs/another-branch")):
        with patch(CREATE_PULL_REQUEST) as create_for_another_branch:
            _finish_run(started.task_id, django_capture_on_commit_callbacks, pushed_branches=pushed_branches)
        create_for_another_branch.assert_not_called()
        assert (
            tasks_facade.read_task_state_entry(started.task_id, team.id, PULL_REQUEST_FAILURE_STATE_KEY)
            == "head_branch_not_issued"
        )
    with patch(CREATE_PULL_REQUEST) as create_after_failed_compare:
        _finish_run(started.task_id, django_capture_on_commit_callbacks, compare_status_code=500)
    create_after_failed_compare.assert_not_called()
    for changed_files, refusal in (
        ((DOCS_PAGE_PATH, WORKFLOW_PATH), "changed_paths_outside_docs"),
        (({"filename": DOCS_PAGE_PATH, "previous_filename": WORKFLOW_PATH},), "changed_paths_outside_docs"),
        ((SIBLING_OF_DOCS_PATH,), "changed_paths_outside_docs"),
        ((DOCS_PAGE_PATH,) * COMPARE_FILE_LIMIT, "too_many_changed_files"),
    ):
        with patch(CREATE_PULL_REQUEST) as create_for_refused_files:
            requested = _finish_run(started.task_id, django_capture_on_commit_callbacks, changed_files=changed_files)
        create_for_refused_files.assert_not_called()
        assert requested == [f"/repos/PostHog/posthog.com/compare/master...{issued_branch}"]
        assert tasks_facade.read_task_state_entry(started.task_id, team.id, PULL_REQUEST_FAILURE_STATE_KEY) == refusal
    with patch(CREATE_PULL_REQUEST, side_effect=ConnectionError("GitHub unreachable")):
        _finish_run(started.task_id, django_capture_on_commit_callbacks)
    with (
        patch(CREATE_PULL_REQUEST, return_value=opened) as create_pull_request,
        patch(f"{GITHUB}.add_pull_request_labels", return_value={"success": True}) as add_labels,
    ):
        for _ in range(2):
            with django_capture_on_commit_callbacks(execute=True):
                TaskRun.objects.get(task_id=started.task_id).save(update_fields=["output"])

    create_pull_request.assert_called_once()
    assert create_pull_request.call_args.args == ("posthog.com",)
    assert create_pull_request.call_args.kwargs["head_branch"] == _issued_branch(started.task_id)
    assert _issued_branch(started.task_id).startswith("knowledge-writer/")
    assert create_pull_request.call_args.kwargs["draft"] is True
    assert LINK_BACK_START in create_pull_request.call_args.kwargs["body"]
    assert COMMAND.pull_request_url in create_pull_request.call_args.kwargs["body"]

    first_body = create_pull_request.call_args.kwargs["body"]
    section = docs_section(SECTION_PAGE)
    assert section is not None
    label = section_label(section)
    add_labels.assert_called_once_with("posthog.com", 9, [label])
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github((9, "Rewritten by a reviewer."), labels=(label,))),
        patch(START_WORKFLOW),
    ):
        joined = intake.submit(second_verdict, team_id=team.id)
    assert joined.status == "joined"
    assert joined.task_id is not None
    assert joined.pull_request_url == opened["pr_url"]
    assert TaskRun.objects.get(task_id=joined.task_id).branch == DOCS_HEAD["branch"]

    with (
        patch(
            f"{GITHUB}.comment_on_pull_request",
            side_effect=[
                GitHubRateLimitError("rate limited"),
                {"success": False, "status_code": 502},
                {"success": True},
            ],
        ) as comment_for_refused_files,
        patch("products.knowledge_writer.backend.logic.pull_requests.time.sleep"),
    ):
        _finish_run(joined.task_id, django_capture_on_commit_callbacks, changed_files=(WORKFLOW_PATH,))
    assert comment_for_refused_files.call_count == 3
    assert comment_for_refused_files.call_args.args[:2] == ("posthog.com", 9)
    assert second_verdict.request.source_url not in comment_for_refused_files.call_args.args[2]
    assert (
        tasks_facade.read_task_state_entry(joined.task_id, team.id, PULL_REQUEST_FAILURE_STATE_KEY)
        == "changed_paths_outside_docs"
    )
    with (
        patch(f"{GITHUB}.get_pull_request", return_value={"success": True, "state": "open", "body": first_body}),
        patch(f"{GITHUB}.comment_on_pull_request", return_value={"success": True}) as comment,
        patch(f"{GITHUB}.update_pull_request_body") as update_body,
        patch(CREATE_PULL_REQUEST) as second_create,
    ):
        _finish_run(joined.task_id, django_capture_on_commit_callbacks)

    second_create.assert_not_called()
    update_body.assert_not_called()
    comment.assert_called_once()
    assert comment.call_args.args[:2] == ("posthog.com", 9)
    assert "https://github.com/PostHog/posthog/pull/456" in comment.call_args.args[2]
    stored = tasks_facade.read_task_state_entry(joined.task_id, team.id, PULL_REQUEST_STATE_KEY)
    assert isinstance(stored, dict)
    assert stored["number"] == 9


@pytest.mark.django_db
def test_a_finished_writer_run_that_cannot_start_its_publish_workflow_records_why_and_calls_no_github(
    team, writer_env, django_capture_on_commit_callbacks, monkeypatch
) -> None:
    monkeypatch.setattr(KNOWLEDGE_WRITER_ENABLED, lambda team_id: True)
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(_verdict(suggested_page_urls=(SECTION_PAGE,)), team_id=team.id)
    assert started.task_id is not None
    with (
        patch(START_PUBLISH, side_effect=TimeoutError("Temporal unreachable")),
        patch(LIST_PULL_REQUESTS) as github_request,
        patch(CREATE_PULL_REQUEST) as create_pull_request,
    ):
        _finish_run(started.task_id, django_capture_on_commit_callbacks)

    github_request.assert_not_called()
    create_pull_request.assert_not_called()
    failure = tasks_facade.read_task_state_entry(started.task_id, team.id, PULL_REQUEST_FAILURE_STATE_KEY)
    assert failure == "publish_not_started"


@pytest.mark.django_db
def test_a_section_stays_busy_after_its_run_finishes_until_its_publication_settles(
    team, writer_env, django_capture_on_commit_callbacks, monkeypatch
) -> None:
    monkeypatch.setattr(KNOWLEDGE_WRITER_ENABLED, lambda team_id: True)
    monkeypatch.setattr(START_PUBLISH, lambda task_run_id, *, team_id: None)
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(_verdict(suggested_page_urls=(SECTION_PAGE,)), team_id=team.id)
        assert started.task_id is not None
        _finish_run(started.task_id, django_capture_on_commit_callbacks)
        while_publishing = intake.submit(_verdict(456, suggested_page_urls=(SECTION_PAGE,)), team_id=team.id)
        writer = writer_settings()
        assert writer is not None
        with time_machine.travel(timezone.now() + PUBLICATION_LEASE, tick=False):
            busy_after_lease = caps.in_flight_writer_runs(writer).busy_sections
        settle_publication(TaskRun.objects.get(task_id=started.task_id).id, team_id=team.id, has_failed=True)
        after_settling = intake.submit(_verdict(456, suggested_page_urls=(SECTION_PAGE,)), team_id=team.id)

    assert while_publishing.status == "section_busy"
    assert busy_after_lease == frozenset()
    assert after_settling.status == "started"


@pytest.mark.django_db
def test_a_publish_retry_reclaims_the_claim_its_crashed_attempt_left_and_opens_the_pull_request(
    team, writer_env, django_capture_on_commit_callbacks, monkeypatch
) -> None:
    monkeypatch.setattr(KNOWLEDGE_WRITER_ENABLED, lambda team_id: True)
    monkeypatch.setattr(START_PUBLISH, lambda task_run_id, *, team_id: None)
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(_verdict(suggested_page_urls=(SECTION_PAGE,)), team_id=team.id)
    assert started.task_id is not None
    _finish_run(started.task_id, django_capture_on_commit_callbacks)
    run = TaskRun.objects.get(task_id=started.task_id)
    tasks_facade.update_task_state_entry(
        started.task_id, team.id, PUBLICATION_CLAIM_STATE_KEY, lambda current: (publication_claim(run.id), None)
    )
    opened = {"success": True, "pr_url": "https://github.com/PostHog/posthog.com/pull/9", "pr_number": 9}
    with (
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(CREATE_PULL_REQUEST, return_value=opened) as create_pull_request,
        patch(f"{GITHUB}.add_pull_request_labels", return_value={"success": True}),
    ):
        pull_request_url = open_or_join_pull_request(run.id, team_id=team.id)

    create_pull_request.assert_called_once()
    assert pull_request_url == opened["pr_url"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "github_responses, handed_pages, withheld_pages",
    [
        (_open_on_github(published_page_paths=("logs/logql-api",)), (SECTION_PAGE,), (REPOSITORY_SOURCED_PAGE,)),
        (
            _open_on_github(lookup_error=GitHubRateLimitError("rate limited")),
            (),
            (REPOSITORY_SOURCED_PAGE, SECTION_PAGE),
        ),
    ],
)
def test_a_page_sourced_from_this_repository_is_not_handed_to_the_writer(
    team, writer_env, github_responses, handed_pages, withheld_pages
) -> None:
    verdict = _verdict(suggested_page_urls=(REPOSITORY_SOURCED_PAGE, SECTION_PAGE))
    assert verdict.request is not None
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=github_responses),
        patch(START_WORKFLOW),
    ):
        outcome = intake.submit(verdict, team_id=team.id)
    task = tasks_facade.get_task_by_origin_key(team.id, verdict.request.dedupe_id)
    assert outcome.status == "started"
    assert task is not None
    assert all(page in task.description for page in handed_pages)
    assert not any(page in task.description for page in withheld_pages)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "pull_request_url, expected_status",
    [
        ("https://github.com/PostHog/posthog/pull/123", "docs_in_source_repo"),
        ("https://github.com/PostHog/posthog-js/pull/123", "started"),
    ],
)
def test_a_request_whose_every_page_is_sourced_from_its_own_repository_starts_no_writer(
    team, writer_env, pull_request_url, expected_status
) -> None:
    verdict = _verdict(suggested_page_urls=(REPOSITORY_SOURCED_PAGE, SECTION_PAGE))
    assert verdict.request is not None
    verdict = dataclasses.replace(verdict, request=dataclasses.replace(verdict.request, source_url=pull_request_url))
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(
            LIST_PULL_REQUESTS,
            side_effect=_open_on_github(published_page_paths=("logs/logql-api", "session-replay/retention")),
        ),
        patch(START_WORKFLOW) as start_workflow,
    ):
        outcome = intake.submit(verdict, team_id=team.id)

    assert outcome.status == expected_status
    assert start_workflow.called is (expected_status == "started")
    assert (tasks_facade.get_task_by_origin_key(team.id, verdict.request.dedupe_id) is not None) is (
        expected_status == "started"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("author_login, expected_status", [(WRITER_APP_LOGIN, "joined"), ("someone-else", "started")])
def test_only_a_pull_request_the_writer_app_opened_can_be_joined(
    team, writer_env, author_login, expected_status
) -> None:
    verdict = _verdict(suggested_page_urls=(SECTION_PAGE,))
    assert verdict.request is not None
    section = docs_section(SECTION_PAGE)
    assert section is not None
    lookalike_body = f"{LINK_BACK_START}\n{section_marker(section)}"
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github((9, lookalike_body), author_login=author_login)),
        patch(START_WORKFLOW),
    ):
        outcome = intake.submit(verdict, team_id=team.id)
    assert outcome.status == expected_status


@pytest.mark.django_db
@pytest.mark.parametrize("cap", ["daily_run", "open_pull_request"])
def test_no_agent_starts_past_a_cap_and_the_cap_raises_an_alert(team, writer_env, cap, monkeypatch) -> None:
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        intake.submit(_verdict(), team_id=team.id)
    monkeypatch.setattr(caps, "DAILY_RUN_CAP", 1 if cap == "daily_run" else 60)
    monkeypatch.setattr(intake, "OPEN_PULL_REQUEST_CAP", 0 if cap == "open_pull_request" else 10)

    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW) as start_workflow,
        patch(CAPTURE_ALERT) as capture_alert,
    ):
        outcome = intake.submit(_verdict(pull_request_number=456), team_id=team.id)

    assert outcome.status == "capped"
    start_workflow.assert_not_called()
    assert capture_alert.call_args.kwargs["additional_properties"]["cap"] == cap


@pytest.mark.django_db
def test_a_repeat_after_a_failed_run_starts_a_new_run_on_the_same_task(team, user, writer_env) -> None:
    verdict = _verdict()
    renewed_verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(
        dataclasses.replace(COMMAND, head_sha="fff999", note="Only touch the API reference.")
    )
    later_verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(dataclasses.replace(COMMAND, head_sha="eee111"))
    after_refusal_verdict = REGISTRY[DocsRequestSource.COMMAND_TAG].assess(
        dataclasses.replace(COMMAND, head_sha="ddd222")
    )

    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW) as start_workflow,
    ):
        started = intake.submit(verdict, team_id=team.id)
        assert started.task_id is not None
        first_branch = _issued_branch(started.task_id)
        TaskRun.objects.filter(task_id=started.task_id).update(status=TaskRun.Status.FAILED)
        rerun = intake.submit(renewed_verdict, team_id=team.id)
        repeated = intake.submit(renewed_verdict, team_id=team.id)

    assert (rerun.status, rerun.task_id) == ("started", started.task_id)
    assert repeated.status == "duplicate"
    assert start_workflow.call_count == 2
    assert _issued_branch(started.task_id) == first_branch
    new_run = TaskRun.objects.filter(task_id=started.task_id).order_by("-created_at").first()
    assert new_run is not None
    assert new_run.state["pending_dispatch"]["create_pr"] is False
    assert new_run.state["pending_dispatch"]["posthog_mcp_scopes"] == []
    assert new_run.state["inactivity_timeout_seconds"] == WRITER_IDLE_TIMEOUT_SECONDS
    assert new_run.state["github_token_scope"] == "push"
    assert new_run.state["config_snapshot"] == {"connectors": {"mcp_installation_ids": []}}
    assert new_run.state["include_live_context"] is False
    task = Task.objects.get(id=started.task_id)
    assert "fff999" in task.description and "Only touch the API reference." in task.description
    stored_request = tasks_facade.read_task_state_entry(task.id, team.id, REQUEST_STATE_KEY)
    assert (
        isinstance(stored_request, dict) and stored_request["trigger_instructions"] == "Only touch the API reference."
    )
    dispatch_options = start_workflow.call_args.kwargs["options"]
    assert (dispatch_options.create_pr, dispatch_options.posthog_mcp_scopes) == (False, [])

    TaskRun.objects.filter(task_id=started.task_id).update(status=TaskRun.Status.FAILED)
    joined_elsewhere = {"number": 9, "url": "https://github.com/PostHog/posthog.com/pull/9"}
    tasks_facade.update_task_state_entry(
        started.task_id, team.id, JOIN_STATE_KEY, lambda _current: (joined_elsewhere, None)
    )
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        intake.submit(later_verdict, team_id=team.id)
    branch_after_join = _issued_branch(started.task_id)
    assert branch_after_join != first_branch

    TaskRun.objects.filter(task_id=started.task_id).update(status=TaskRun.Status.FAILED)
    tasks_facade.update_task_state_entry(
        started.task_id, team.id, PULL_REQUEST_FAILURE_STATE_KEY, lambda _current: ("changed_paths_outside_docs", None)
    )
    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        intake.submit(after_refusal_verdict, team_id=team.id)
    assert _issued_branch(started.task_id) != branch_after_join


@pytest.mark.django_db
def test_a_rerun_counts_toward_the_daily_run_cap(team, writer_env, monkeypatch) -> None:
    monkeypatch.setattr(caps, "DAILY_RUN_CAP", 2)

    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
        patch(CAPTURE_ALERT),
    ):
        started = intake.submit(_verdict(), team_id=team.id)
        assert started.task_id is not None
        TaskRun.objects.filter(task_id=started.task_id).update(status=TaskRun.Status.FAILED)
        rerun = intake.submit(_verdict(), team_id=team.id)
        next_request = intake.submit(_verdict(pull_request_number=456), team_id=team.id)

    assert (started.status, rerun.status, next_request.status) == ("started", "started", "capped")


@pytest.mark.django_db
def test_two_requests_that_both_saw_the_failed_run_start_one_rerun(team, writer_env) -> None:
    verdict = _verdict()
    assert verdict.request is not None

    with (
        patch(FLAG_CHECK, return_value=True),
        patch(LIST_PULL_REQUESTS, side_effect=_open_on_github()),
        patch(START_WORKFLOW),
    ):
        started = intake.submit(verdict, team_id=team.id)
        assert started.task_id is not None
        TaskRun.objects.filter(task_id=started.task_id).update(status=TaskRun.Status.FAILED)
        task_seen_failed = tasks_facade.get_task_by_origin_key(team.id, verdict.request.dedupe_id)
        with patch.object(intake.tasks_facade, "get_task_by_origin_key", return_value=task_seen_failed):
            first = intake.submit(verdict, team_id=team.id)
            second = intake.submit(verdict, team_id=team.id)

    assert (first.status, second.status) == ("started", "duplicate")
    assert TaskRun.objects.filter(task_id=started.task_id).count() == 2
