import random

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.code_workstreams.activities.list_active_teams import list_active_code_teams

FLAG_PATH = (
    "products.tasks.backend.temporal.code_workstreams.activities.list_active_teams.posthoganalytics.feature_enabled"
)


def _org() -> Organization:
    return Organization.objects.create(name=f"WorkstreamsOrg-{random.randint(1, 99999)}")


def _team(org: Organization) -> Team:
    return Team.objects.create(organization=org, name=f"WorkstreamsTeam-{random.randint(1, 99999)}")


def _active_team(
    org: Organization,
    origin_product: Task.OriginProduct = Task.OriginProduct.USER_CREATED,
) -> Team:
    team = _team(org)
    task = Task.objects.create(
        team=team,
        title="t",
        description="d",
        origin_product=origin_product,
    )
    TaskRun.objects.create(task=task, team=team, status=TaskRun.Status.COMPLETED)
    return team


@pytest.mark.django_db(transaction=True)
def test_only_returns_teams_whose_org_has_flag(activity_environment):
    enabled_org = _org()
    disabled_org = _org()
    enabled_team = _active_team(enabled_org)
    _active_team(disabled_org)

    def _flag(key, distinct_id=None, **kwargs):
        return distinct_id == str(enabled_org.id)

    with patch(FLAG_PATH, side_effect=_flag):
        result = activity_environment.run(list_active_code_teams, None)

    assert result.team_ids == [enabled_team.id]
    assert result.truncated is False


@pytest.mark.django_db(transaction=True)
def test_flag_checked_once_per_org_not_per_team(activity_environment):
    org = _org()
    team_a = _active_team(org)
    team_b = _active_team(org)

    with patch(FLAG_PATH, return_value=True) as flag:
        result = activity_environment.run(list_active_code_teams, None)

    assert sorted(result.team_ids) == sorted([team_a.id, team_b.id])
    assert flag.call_count == 1


@pytest.mark.django_db(transaction=True)
def test_excludes_org_when_flag_check_raises(activity_environment):
    org = _org()
    _active_team(org)

    with patch(FLAG_PATH, side_effect=RuntimeError("flag service down")):
        result = activity_environment.run(list_active_code_teams, None)

    assert result.team_ids == []


@pytest.mark.django_db(transaction=True)
def test_returns_empty_when_no_orgs_enabled(activity_environment):
    org = _org()
    _active_team(org)

    with patch(FLAG_PATH, return_value=False):
        result = activity_environment.run(list_active_code_teams, None)

    assert result.team_ids == []
    assert result.truncated is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "origin_product",
    [
        Task.OriginProduct.USER_CREATED,
        Task.OriginProduct.SLACK,
        Task.OriginProduct.AUTOMATION,
    ],
)
def test_includes_teams_with_posthog_code_origin(activity_environment, origin_product):
    org = _org()
    team = _active_team(org, origin_product)

    with patch(FLAG_PATH, return_value=True):
        result = activity_environment.run(list_active_code_teams, None)

    assert result.team_ids == [team.id]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "origin_product",
    [
        Task.OriginProduct.ERROR_TRACKING,
        Task.OriginProduct.EVAL_CLUSTERS,
        Task.OriginProduct.SUPPORT_QUEUE,
        Task.OriginProduct.SESSION_SUMMARIES,
        Task.OriginProduct.SIGNAL_REPORT,
        Task.OriginProduct.SIGNALS_SCOUT,
    ],
)
def test_excludes_teams_with_only_non_code_origin(activity_environment, origin_product):
    org = _org()
    _active_team(org, origin_product)

    # Org has the flag on, but its only recent run came from another product on
    # the shared tasks infra — it must not be pulled into workstream evaluation.
    with patch(FLAG_PATH, return_value=True):
        result = activity_environment.run(list_active_code_teams, None)

    assert result.team_ids == []


@pytest.mark.django_db(transaction=True)
def test_includes_team_with_mix_of_code_and_non_code_runs(activity_environment):
    org = _org()
    team = _team(org)
    code_task = Task.objects.create(
        team=team, title="t", description="d", origin_product=Task.OriginProduct.USER_CREATED
    )
    other_task = Task.objects.create(
        team=team, title="t", description="d", origin_product=Task.OriginProduct.ERROR_TRACKING
    )
    TaskRun.objects.create(task=code_task, team=team, status=TaskRun.Status.COMPLETED)
    TaskRun.objects.create(task=other_task, team=team, status=TaskRun.Status.COMPLETED)

    # A single PostHog Code run qualifies the team even amid other-product runs.
    with patch(FLAG_PATH, return_value=True):
        result = activity_environment.run(list_active_code_teams, None)

    assert result.team_ids == [team.id]
