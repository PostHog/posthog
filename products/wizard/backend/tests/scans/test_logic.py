from datetime import UTC, datetime, timedelta

import pytest

from posthog.models import Team

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


def _scan(team: Team, session_id: str, hours: int, kinds: list[str], workspace: str = WORKSPACE) -> WizardScanResult:
    return wizard_facade.record_scan(
        RecordWizardScanInput(
            team_id=team.id,
            created_by_id=None,
            session_id=session_id,
            program="posthog-integration",
            wizard_version="2.0.0",
            workspace_fingerprint=workspace,
            scanned_at=START + timedelta(hours=hours),
            tools=tuple(
                WizardScanTool(kind=kind, signals=(WizardScanSignal(source="npm", name=kind.lower(), file=None),))
                for kind in kinds
            ),
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
    assert tools["Amplitude"].competes_with == ["product_analytics"]
    assert tools["Stripe"].warehouse_source_type == "Stripe"
    assert (tools["NotInTheCatalog"].warehouse_source_type, tools["NotInTheCatalog"].competes_with) == (None, [])

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
def test_replayed_session_changes_nothing(team: Team) -> None:
    first = _scan(team, "s1", 0, ["Stripe"])
    replay = _scan(team, "s1", 1, ["Amplitude"])

    assert replay == WizardScanResult(id=first.id, created=False)
    assert set(_tools(team)) == {"Stripe"}


@pytest.mark.django_db
def test_scan_of_one_workspace_leaves_other_workspaces_alone(team: Team) -> None:
    _scan(team, "s1", 0, ["Stripe"])
    _scan(team, "s2", 1, [], workspace=OTHER_WORKSPACE)

    assert _tools(team)["Stripe"].removed_at is None
