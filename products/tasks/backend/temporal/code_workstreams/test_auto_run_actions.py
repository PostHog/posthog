import random

import pytest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from posthog.models import Organization, Team, User

from products.tasks.backend.models import CodeWorkflowConfig, CodeWorkstream, Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.activities.auto_run_actions import (
    AutoRunWorkstreamActionsInput,
    auto_run_workstream_actions,
)

FLAG_PATH = (
    "products.tasks.backend.temporal.code_workstreams.activities.auto_run_actions.posthoganalytics.feature_enabled"
)
CREATE_AND_RUN_PATH = "products.tasks.backend.temporal.code_workstreams.activities.auto_run_actions.Task.create_and_run"


def _action(**overrides) -> dict:
    base = {"id": "fix_ci", "label": "Fix CI", "skillId": "", "prompt": "Fix the CI", "auto": True}
    base.update(overrides)
    return base


def _org() -> Organization:
    return Organization.objects.create(name=f"AutoRunOrg-{random.randint(1, 99999)}")


def _user(org: Organization) -> User:
    return User.objects.create_and_join(org, f"auto-{random.randint(1, 99999)}@posthog.com", None)


def _config(team: Team, user: User, bindings: dict) -> CodeWorkflowConfig:
    return CodeWorkflowConfig.objects.create(team=team, user=user, bindings=bindings)


def _workstream(team: Team, user: User, **overrides) -> CodeWorkstream:
    defaults = {
        "key": "pr:https://github.com/org/repo/pull/1",
        "repo_name": "repo",
        "repo_full_path": "org/repo",
        "branch": "feat/x",
        "pr_url": "https://github.com/org/repo/pull/1",
        "situations": ["ci_failing"],
        "primary_situation": "ci_failing",
        "state": CodeWorkstream.WorkstreamState.ATTENTION,
        "tasks": [],
        "last_activity_at": timezone.now(),
    }
    defaults.update(overrides)
    return CodeWorkstream.objects.create(team=team, user=user, **defaults)


@pytest.fixture
def setup():
    org = _org()
    team = Team.objects.create(organization=org, name=f"AutoRunTeam-{random.randint(1, 99999)}")
    user = _user(org)
    return org, team, user


@pytest.mark.django_db(transaction=True)
def test_fires_auto_action_for_primary_situation(setup, activity_environment):
    org, team, user = setup
    _config(team, user, {"ci_failing": [_action()]})
    ws = _workstream(team, user)

    fake_task = MagicMock(id="task-123")
    with patch(FLAG_PATH, return_value=True), patch(CREATE_AND_RUN_PATH, return_value=fake_task) as create:
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 1
    assert create.call_count == 1
    kwargs = create.call_args.kwargs
    assert kwargs["repository"] == "org/repo"
    assert kwargs["branch"] == "feat/x"
    assert kwargs["home_quick_action"] == "Fix CI"
    assert kwargs["initial_permission_mode"] == "auto"
    # Marker persisted so it won't re-fire next cycle.
    ws.refresh_from_db()
    assert "fix_ci" in ws.auto_run_state
    assert ws.auto_run_state["fix_ci"]["task_id"] == "task-123"


@pytest.mark.django_db(transaction=True)
def test_skips_when_workstream_has_running_task(setup, activity_environment):
    org, team, user = setup
    _config(team, user, {"ci_failing": [_action()]})
    task = Task.objects.create(team=team, title="t", description="d", origin_product=Task.OriginProduct.USER_CREATED)
    TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.IN_PROGRESS)
    _workstream(team, user, tasks=[{"id": str(task.id), "title": "t", "status": "in_progress"}])

    with patch(FLAG_PATH, return_value=True), patch(CREATE_AND_RUN_PATH) as create:
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 0
    create.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_skips_when_already_fired(setup, activity_environment):
    org, team, user = setup
    _config(team, user, {"ci_failing": [_action()]})
    _workstream(team, user, auto_run_state={"fix_ci": {"fired_at": "2026-01-01T00:00:00Z", "task_id": "old"}})

    with patch(FLAG_PATH, return_value=True), patch(CREATE_AND_RUN_PATH) as create:
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 0
    create.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_skips_non_auto_action(setup, activity_environment):
    org, team, user = setup
    _config(team, user, {"ci_failing": [_action(auto=False)]})
    _workstream(team, user)

    with patch(FLAG_PATH, return_value=True), patch(CREATE_AND_RUN_PATH) as create:
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 0
    create.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_only_fires_for_primary_situation(setup, activity_environment):
    org, team, user = setup
    # ci_failing has an auto action, but the workstream's primary is in_review.
    _config(team, user, {"ci_failing": [_action()], "in_review": []})
    _workstream(team, user, situations=["ci_failing", "in_review"], primary_situation="in_review")

    with patch(FLAG_PATH, return_value=True), patch(CREATE_AND_RUN_PATH) as create:
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 0
    create.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_no_op_when_flag_disabled(setup, activity_environment):
    org, team, user = setup
    _config(team, user, {"ci_failing": [_action()]})
    _workstream(team, user)

    with patch(FLAG_PATH, return_value=False), patch(CREATE_AND_RUN_PATH) as create:
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 0
    create.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_creation_failure_does_not_persist_marker(setup, activity_environment):
    org, team, user = setup
    _config(team, user, {"ci_failing": [_action()]})
    ws = _workstream(team, user)

    with patch(FLAG_PATH, return_value=True), patch(CREATE_AND_RUN_PATH, side_effect=ValueError("no github")):
        result = activity_environment.run(auto_run_workstream_actions, AutoRunWorkstreamActionsInput(team_id=team.id))

    assert result.fired == 0
    ws.refresh_from_db()
    assert ws.auto_run_state == {}
