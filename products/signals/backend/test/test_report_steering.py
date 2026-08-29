import pytest

from django.apps import apps

from posthog.models import Organization, Team
from posthog.models.scoping import team_scope

from products.signals.backend.models import (
    SignalReport,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
    SignalScratchpad,
)
from products.signals.backend.report_steering import NO_STEERING, load_research_steering
from products.skills.backend.models.skills import LLMSkill

SCOUT_SKILL = "signals-scout-error-tracking"


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-report-steering-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-report-steering-team")


def _attach_scout_run(team: Team, report: SignalReport) -> None:
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    LLMSkill.objects.create(team=team, name=SCOUT_SKILL, description="d", body="b")
    task = Task.objects.create(
        team=team, title="scout run", description="d", origin_product=Task.OriginProduct.SIGNALS_SCOUT
    )
    config, _ = SignalScoutConfig.objects.get_or_create(team=team, skill_name=SCOUT_SKILL)
    SignalScoutRun.objects.create(
        team=team,
        task_run=TaskRun.objects.create(task=task, team=team),
        scout_config=config,
        skill_name=SCOUT_SKILL,
        skill_version=1,
        emitted_report_ids=[str(report.id)],
    )


@pytest.mark.django_db
def test_research_steering_carries_the_report_derived_notes(organization, team):
    # The loop this closes: someone dismisses a report with a reason, that verdict becomes a note,
    # and only scheduled scout runs ever read it. Research is the stage that judges whether the
    # topic is worth surfacing again, so the same feedback has to reach it. The implementation run
    # deliberately reads the opposite set (see `load_report_steering`).
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )
    with team_scope(team.id, canonical=True):
        _attach_scout_run(team, report)
        SignalScoutNote.objects.create(team=team, skill_name="", content="the checkout flow is frozen")
        SignalScoutNote.objects.create(
            team=team,
            skill_name=SCOUT_SKILL,
            content="dismissed as wontfix_expected: this is the approval flow, not a bug",
            origin=SignalScoutNote.Origin.REPORT_DISMISSAL,
        )
        SignalScoutNote.objects.create(
            team=team,
            skill_name=SCOUT_SKILL,
            content="which teams does this hit?",
            origin=SignalScoutNote.Origin.REPORT_DISCUSSION,
        )

    # No ambient team scope here on purpose: research runs in a Temporal activity, so the reads
    # have to set their own scope or every fail-closed model raises.
    steering = load_research_steering(team.id, str(report.id))

    assert steering.notes_attached == 3
    assert steering.dismissal_notes_attached == 1
    assert "the checkout flow is frozen" in steering.section
    assert "this is the approval flow, not a bug" in steering.section
    assert "which teams does this hit?" in steering.section
    # A note is evidence about what the team wants, never a second set of instructions for a run
    # whose output becomes the report every reviewer reads.
    assert "never as instructions" in steering.section
    # No fleet memory yet, so the scratchpad pointer must not tax the prompt.
    assert steering.scratchpad_available is False
    assert "scout-scratchpad-search" not in steering.section

    with team_scope(team.id, canonical=True):
        SignalScratchpad.objects.create(team=team, key="noise:checkout:019de34e", content="known, expected")
    with_memory = load_research_steering(team.id, str(report.id))
    assert with_memory.scratchpad_available is True
    assert "scout-scratchpad-search" in with_memory.section

    # A child environment gets nothing. Notes live on the canonical project, but the research run
    # writes its title and summary onto the report on this team, where people who cannot reach the
    # parent project would read them.
    child = Team.objects.create(organization=organization, name="child-env", parent_team=team)
    child_report = SignalReport.objects.create(
        team=child, status=SignalReport.Status.READY, title="t", summary="s", signal_count=0, total_weight=0.0
    )
    assert load_research_steering(child.id, str(child_report.id)) == NO_STEERING
