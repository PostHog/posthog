from __future__ import annotations

import json
import random

import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.temporal.dreaming.briefing import Briefing, BriefingItem
from products.signals.backend.temporal.dreaming.delivery import (
    DREAMING_BRIEFING_TITLE,
    deliver_briefing,
    deliver_briefing_to_inbox,
    deliver_briefing_to_slack,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name=f"DelivOrg-{random.randint(1, 99999)}")


@pytest.fixture
def team(org: Organization) -> Team:
    return Team.objects.create(organization=org, name=f"DelivTeam-{random.randint(1, 99999)}")


def _briefing() -> Briefing:
    return Briefing(
        intro="here's the scoop",
        items=(
            BriefingItem("Thing one", "Detail one"),
            BriefingItem("Thing two", "Detail two"),
            BriefingItem("Thing three", "Detail three"),
        ),
    )


class TestInboxDelivery:
    def test_creates_ready_report_with_artefact(self, team: Team):
        report_id = deliver_briefing_to_inbox(team.id, _briefing())

        report = SignalReport.objects.get(id=report_id)
        assert report.status == SignalReport.Status.READY
        assert report.title == DREAMING_BRIEFING_TITLE
        assert "Thing one" in (report.summary or "")

        artefact = SignalReportArtefact.objects.get(report=report)
        assert artefact.type == SignalReportArtefact.ArtefactType.DREAMING_BRIEFING
        data = json.loads(artefact.content)
        assert len(data["items"]) == 3

    def test_replaces_prior_briefing(self, team: Team):
        first = deliver_briefing_to_inbox(team.id, _briefing())
        second = deliver_briefing_to_inbox(team.id, _briefing())

        old = SignalReport.objects.get(id=first)
        new = SignalReport.objects.get(id=second)
        assert old.status == SignalReport.Status.DELETED
        assert new.status == SignalReport.Status.READY
        # Exactly one live briefing remains.
        live = SignalReport.objects.filter(
            team_id=team.id, title__startswith=DREAMING_BRIEFING_TITLE, status=SignalReport.Status.READY
        )
        assert live.count() == 1


class TestSlackDelivery:
    def test_no_integration_returns_false(self, team: Team):
        assert deliver_briefing_to_slack(team.id, _briefing()) is False

    def test_posts_to_team_channel(self, team: Team):
        Integration.objects.create(team=team, kind="slack", integration_id="T1", config={}, sensitive_config={})
        mock_client = MagicMock()

        with (
            patch(
                "products.signals.backend.temporal.dreaming.delivery._team_briefing_channel",
                return_value="C123|#general",
            ),
            patch("products.signals.backend.temporal.dreaming.delivery.SlackIntegration") as MockSlack,
        ):
            MockSlack.return_value.client = mock_client
            posted = deliver_briefing_to_slack(team.id, _briefing())

        assert posted is True
        mock_client.chat_postMessage.assert_called_once()
        _, kwargs = mock_client.chat_postMessage.call_args
        assert kwargs["channel"] == "C123"

    def test_no_channel_configured_returns_false(self, team: Team):
        Integration.objects.create(team=team, kind="slack", integration_id="T1", config={}, sensitive_config={})
        with patch(
            "products.signals.backend.temporal.dreaming.delivery._team_briefing_channel",
            return_value=None,
        ):
            assert deliver_briefing_to_slack(team.id, _briefing()) is False


class TestDeliverBoth:
    def test_inbox_written_even_when_slack_absent(self, team: Team):
        report_id, slack_posted = deliver_briefing(team.id, _briefing())
        assert slack_posted is False
        assert SignalReport.objects.filter(id=report_id).exists()
