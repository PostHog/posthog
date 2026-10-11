import datetime as dt

import pytest

from django.apps import apps
from django.utils import timezone

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope

from products.signals.backend.facade.api import scouts_for_source
from products.signals.backend.models import SignalScoutConfig, SignalScoutRun

SOURCE_PRODUCT = "replay_vision"
SOURCE_ID = "scanner-1"


@pytest.mark.django_db
def test_scouts_for_source_reports_when_the_newest_run_started() -> None:
    # Replay vision pauses a turned-off scanner's scout once a run starts after the scanner stopped.
    # An older run here would pause the scout before its final report.
    org = Organization.objects.create(name="test-source-scouts-org")
    team = Team.objects.create(organization=org, name="test-source-scouts-team")
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    now = timezone.now()

    with team_scope(team.id, canonical=True):
        ran = SignalScoutConfig.objects.create(
            team=team, skill_name="ran-scout", source_product=SOURCE_PRODUCT, source_id=SOURCE_ID
        )
        SignalScoutConfig.objects.create(
            team=team, skill_name="idle-scout", source_product=SOURCE_PRODUCT, source_id=SOURCE_ID
        )
        task = Task.objects.create(
            team=team, title="scout run", description="d", origin_product=Task.OriginProduct.SIGNALS_SCOUT
        )
        for hours_ago in (2, 1):
            run = SignalScoutRun.objects.create(
                team=team,
                task_run=TaskRun.objects.create(task=task, team=team),
                scout_config=ran,
                skill_name=ran.skill_name,
                skill_version=1,
            )
            SignalScoutRun.objects.filter(pk=run.pk).update(created_at=now - dt.timedelta(hours=hours_ago))

    scouts = {scout.skill_name: scout for scout in scouts_for_source(team.id, SOURCE_PRODUCT, SOURCE_ID)}

    assert scouts["ran-scout"].last_run_started_at == now - dt.timedelta(hours=1)
    assert scouts["idle-scout"].last_run_started_at is None
