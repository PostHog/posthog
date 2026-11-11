from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from posthog.models import Organization, Team, User

from products.wizard.backend.facade import api as wizard_facade
from products.wizard.backend.facade.contracts import (
    RecordWizardScanInput,
    WizardScanResult,
    WizardScanSignal,
    WizardScanTool,
)
from products.wizard.backend.models import WizardDetectedTool

WORKSPACE = "a" * 64
OTHER_WORKSPACE = "b" * 64
START = datetime(2026, 5, 19, 10, 0, tzinfo=UTC)


def _scan(
    team: Team,
    session_id: str,
    hours: int,
    kinds: list[str],
    workspace: str = WORKSPACE,
    created_by_id: int | None = None,
    complete: bool = True,
) -> WizardScanResult:
    return wizard_facade.record_scan(
        RecordWizardScanInput(
            team_id=team.id,
            created_by_id=created_by_id,
            session_id=session_id,
            program="posthog-integration",
            wizard_version="2.0.0",
            workspace_fingerprint=workspace,
            scanned_at=START + timedelta(hours=hours),
            tools=tuple(
                WizardScanTool(kind=kind, signals=(WizardScanSignal(source="npm", name=kind.lower(), file=None),))
                for kind in kinds
            ),
            complete=complete,
        )
    )


def _tools(team: Team, workspace: str = WORKSPACE) -> dict[str, WizardDetectedTool]:
    return {
        row.kind: row for row in WizardDetectedTool.objects.for_team(team.id).filter(workspace_fingerprint=workspace)
    }


@pytest.mark.django_db
def test_tracks_tools_across_scans(team: Team) -> None:
    first = _scan(team, "s1", 0, ["Stripe", "Amplitude", "NotInTheCatalog"])
    second = _scan(team, "s2", 1, ["Stripe"])

    tools = _tools(team)
    assert tools["Amplitude"].removed_in_scan_id == second.id
    assert tools["Stripe"].removed_at is None
    assert tools["Stripe"].last_seen_scan_id == second.id
    assert tools["Amplitude"].alternative_to == ["product_analytics"]
    assert tools["Stripe"].warehouse_source_type == "Stripe"
    assert (tools["NotInTheCatalog"].warehouse_source_type, tools["NotInTheCatalog"].alternative_to) == (None, [])

    third = _scan(team, "s3", 2, ["Stripe", "Amplitude"])

    amplitude = _tools(team)["Amplitude"]
    assert (amplitude.removed_in_scan_id, amplitude.removed_at) == (None, None)
    assert amplitude.first_seen_scan_id == first.id
    assert amplitude.last_seen_scan_id == third.id


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scans, last_seen_session, removed_session",
    [
        pytest.param([("newer", 2, ["Stripe"]), ("older", 1, [])], "newer", None, id="late_empty_scan"),
        pytest.param(
            [("seen", 0, ["Stripe"]), ("removed", 2, []), ("late", 1, ["Stripe"])],
            "seen",
            "removed",
            id="late_sighting_after_removal",
        ),
        pytest.param(
            [("seen", 0, ["Stripe"]), ("removed", 2, []), ("still_absent", 4, []), ("late", 3, ["Stripe"])],
            "seen",
            "removed",
            id="late_sighting_after_repeated_absence",
        ),
    ],
)
def test_older_scan_arriving_late_does_not_rewind_state(
    team: Team, scans: list[tuple[str, int, list[str]]], last_seen_session: str, removed_session: str | None
) -> None:
    ids = {session_id: _scan(team, session_id, hours, kinds).id for session_id, hours, kinds in scans}

    stripe = _tools(team)["Stripe"]
    assert stripe.last_seen_scan_id == ids[last_seen_session]
    assert stripe.removed_in_scan_id == (ids[removed_session] if removed_session else None)


@pytest.mark.django_db
@pytest.mark.parametrize("through_child_environment", [False, True])
def test_replayed_session_changes_nothing(team: Team, through_child_environment: bool) -> None:
    reporting_team = (
        Team.objects.create(organization=team.organization, parent_team=team, name="env")
        if through_child_environment
        else team
    )
    first = _scan(reporting_team, "s1", 0, ["Stripe"])
    replay = _scan(reporting_team, "s1", 1, ["Amplitude"])

    assert replay == WizardScanResult(id=first.id, created=False)
    assert set(_tools(team)) == {"Stripe"}


@pytest.mark.django_db
def test_scan_of_one_workspace_leaves_other_workspaces_alone(team: Team) -> None:
    _scan(team, "s1", 0, ["Stripe"])
    _scan(team, "s2", 1, [], workspace=OTHER_WORKSPACE)

    assert _tools(team)["Stripe"].removed_at is None


@pytest.mark.django_db
def test_partial_scan_adds_what_it_saw_and_removes_nothing(team: Team) -> None:
    _scan(team, "s1", 0, ["Stripe", "Amplitude"])
    _scan(team, "s2", 1, ["Stripe", "Sentry"], complete=False)

    tools = _tools(team)
    assert {kind for kind, row in tools.items() if row.removed_at is None} == {"Stripe", "Amplitude", "Sentry"}


@pytest.mark.django_db
def test_reports_posthog_alternative_changes_once_per_scan(team: Team, django_capture_on_commit_callbacks) -> None:
    scans = [
        ("s1", 0, ["Amplitude", "Stripe"]),
        ("s2", 1, []),
        ("s2", 2, ["Amplitude"]),
        ("s3", 3, ["Amplitude"]),
        ("s4", 4, []),
    ]
    with patch("posthoganalytics.capture") as capture:
        for session_id, hours, kinds in scans:
            with django_capture_on_commit_callbacks(execute=True):
                _scan(team, session_id, hours, kinds)

    events = [
        (
            call.kwargs["event"],
            call.kwargs["properties"]["kind"],
            call.kwargs["properties"].get("first_detection"),
            call.kwargs["properties"].get("returned"),
        )
        for call in capture.call_args_list
    ]
    assert events == [
        ("wizard posthog alternative detected", "Amplitude", True, False),
        ("wizard posthog alternative removed", "Amplitude", None, None),
        ("wizard posthog alternative detected", "Amplitude", False, True),
        ("wizard posthog alternative removed", "Amplitude", None, None),
    ]
    first_properties = capture.call_args_list[0].kwargs["properties"]
    assert (first_properties["alternative_to"], first_properties["wizard_version"]) == (["product_analytics"], "2.0.0")


@pytest.mark.django_db
def test_failing_posthog_alternative_report_keeps_the_scan(team: Team, django_capture_on_commit_callbacks) -> None:
    with (
        patch("products.wizard.backend.logic.scans.report_user_or_team_action", side_effect=RuntimeError),
        django_capture_on_commit_callbacks(execute=True),
    ):
        result = _scan(team, "s1", 0, ["Amplitude"])

    assert result.created is True
    assert set(_tools(team)) == {"Amplitude"}


@pytest.mark.django_db
def test_posthog_alternative_events_belong_to_the_scanned_projects_organization(
    team: Team, django_capture_on_commit_callbacks
) -> None:
    other_organization = Organization.objects.create(name="Other organization")
    user = User.objects.create_and_join(other_organization, "scanner@example.com", None)
    user.organizations.add(team.organization)
    assert user.current_organization == other_organization

    with patch("posthoganalytics.capture") as capture, django_capture_on_commit_callbacks(execute=True):
        _scan(team, "s1", 0, ["Amplitude"], created_by_id=user.id)

    assert capture.call_args.kwargs["groups"]["organization"] == str(team.organization_id)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scans, same_organization, expected",
    [
        ([("s1", 0, ["Stripe", "OpenAI"])], True, True),
        ([("s1", 0, ["OpenAI"]), ("s2", 1, ["Stripe"])], True, False),
        ([("s1", 0, ["Stripe"])], True, False),
        ([("s1", 0, ["OpenAI"])], False, False),
    ],
    ids=["active_in_another_project", "removed_by_a_later_scan", "other_kind", "other_organization"],
)
def test_organization_has_detected_tool_reads_every_project_in_the_organization(
    team: Team, scans: list[tuple[str, int, list[str]]], same_organization: bool, expected: bool
) -> None:
    organization = team.organization if same_organization else Organization.objects.create(name="Other organization")
    scanned_team = Team.objects.create_with_data(initiating_user=None, organization=organization)
    for session_id, hours, kinds in scans:
        _scan(scanned_team, session_id, hours, kinds)

    assert (
        wizard_facade.organization_has_detected_tool(organization_id=str(team.organization_id), kinds=["OpenAI"])
        is expected
    )
