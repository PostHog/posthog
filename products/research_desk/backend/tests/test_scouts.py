from datetime import UTC, datetime, timedelta
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.cohorts.backend.models.cohort import Cohort
from products.customer_analytics.backend.facade.contracts import MeetingParticipantView, SyncedMeeting
from products.research_desk.backend.facade import api, contracts
from products.research_desk.backend.facade.enums import SessionStatus, SourceKind, SourceOrigin
from products.research_desk.backend.logic.calendar_scout import session_input_for_meeting
from products.research_desk.backend.logic.source_discovery import looks_like_contacted_cohort, looks_like_recruiting
from products.research_desk.backend.models import ResearchSession, ResearchSource

PRODUCT_DATABASES = {"default", "research_desk_db_writer", "research_desk_db_reader"}
NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


def _meeting(
    title: str = "User interview: dashboards",
    emails: tuple[str, ...] = ("host@posthog.com", "Ada@Example.com"),
    status: str = "confirmed",
    start: datetime = NOW + timedelta(hours=2),
    meet_code: str = "abc-defg-hij",
) -> SyncedMeeting:
    return SyncedMeeting(
        id=uuid4(),
        title=title,
        start_time=start,
        end_time=start + timedelta(minutes=30),
        organizer_email="host@posthog.com",
        status=status,
        meet_code=meet_code,
        participants=[
            MeetingParticipantView(
                email=e, display_name="", response_status="accepted", is_organizer=i == 0, person_id=None
            )
            for i, e in enumerate(emails)
        ],
    )


class TestSessionMapping(SimpleTestCase):
    @parameterized.expand(
        [
            ("sales_call_is_not_research", _meeting(title="Pricing call with Example Inc")),
            ("internal_only", _meeting(emails=("host@posthog.com", "teammate@posthog.com"))),
        ]
    )
    def test_skips_non_research_meetings(self, _name: str, meeting: SyncedMeeting) -> None:
        assert session_input_for_meeting(1, meeting, NOW) is None

    @parameterized.expand(
        [
            ("upcoming", _meeting(), SessionStatus.SCHEDULED),
            ("finished", _meeting(start=NOW - timedelta(hours=2)), SessionStatus.HELD),
            ("cancelled", _meeting(status="cancelled"), SessionStatus.CANCELLED),
        ]
    )
    def test_maps_status(self, _name: str, meeting: SyncedMeeting, expected: SessionStatus) -> None:
        data = session_input_for_meeting(1, meeting, NOW)

        assert data is not None
        assert data.status == expected
        assert data.internal_emails == ("host@posthog.com",)
        assert data.external_emails == ("ada@example.com",)
        assert data.meeting_url == "https://meet.google.com/abc-defg-hij"

    @parameterized.expand(
        [
            ("Quick chat about how you use exports?", True),
            ("Got 20 minutes for an interview?", True),
            ("Your weekly digest", False),
            ("Workflows: AI and MCPs call it", False),
        ]
    )
    def test_recruiting_text(self, text: str, expected: bool) -> None:
        assert looks_like_recruiting(text) is expected

    @parameterized.expand(
        [
            ("Exports already contacted", True),
            ("Q3 interviews - reached out", True),
            ("Daily active exporters", False),
        ]
    )
    def test_contacted_cohort_names(self, name: str, expected: bool) -> None:
        assert looks_like_contacted_cohort(name) is expected


class TestScouts(ClickhouseTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def test_source_discovery_registers_each_kind_once_and_respects_rejections(self) -> None:
        now = timezone.now()
        for workflow_id, subject in [
            ("wf-interviews", "Quick chat about your exports?"),
            ("wf-marketing", "Your weekly digest"),
            ("wf-rejected", "Could we get your feedback? Book an interview"),
        ]:
            _create_event(
                team=self.team,
                event="$workflows_email_sent",
                distinct_id="someone",
                properties={"$workflow_id": workflow_id, "$email_subject": subject},
                timestamp=now - timedelta(days=1),
            )
        _create_event(
            team=self.team,
            event="survey shown",
            distinct_id="someone",
            properties={"$survey_id": "survey-1", "$survey_name": "User interviews: export formats"},
            timestamp=now - timedelta(days=1),
        )
        _create_event(
            team=self.team,
            event="mcp interview invitation sent",
            distinct_id="someone",
            timestamp=now - timedelta(days=1),
        )
        flush_persons_and_events()
        cohort = Cohort.objects.create(team=self.team, name="Exports already contacted", is_static=True)
        Cohort.objects.create(team=self.team, name="Heavy exporters", is_static=True)
        with team_scope(self.team.id):
            rejected = api.create_source(
                contracts.CreateResearchSourceInput(
                    team_id=self.team.id, kind=SourceKind.WORKFLOW, external_id="wf-rejected", label="Not research"
                )
            )
            api.update_source(self.team.id, rejected.id, contracts.UpdateResearchSourceInput(active=False))

        first = api.run_source_discovery(self.team.id)
        second = api.run_source_discovery(self.team.id)

        assert sorted((s.kind, s.external_id) for s in first.sources_created) == sorted(
            [
                (SourceKind.WORKFLOW, "wf-interviews"),
                (SourceKind.SURVEY, "survey-1"),
                (SourceKind.COHORT, str(cohort.id)),
                (SourceKind.EVENT, "mcp interview invitation sent"),
            ]
        )
        assert {s.origin for s in first.sources_created} == {SourceOrigin.SCOUT}
        assert second.sources_created == []
        with team_scope(self.team.id):
            assert ResearchSource.objects.count() == 5

    def test_calendar_scout_upserts_sessions_idempotently(self) -> None:
        meeting = _meeting(start=timezone.now() + timedelta(hours=3))
        cancelled = SyncedMeeting(**{**meeting.__dict__, "status": "cancelled"})

        with patch(
            "products.customer_analytics.backend.facade.api.list_meetings_in_window",
            side_effect=[[meeting, _meeting(title="Pricing call")], [cancelled]],
        ):
            first = api.run_calendar_scout(self.team.id)
            second = api.run_calendar_scout(self.team.id)

        assert (first.sessions_created, second.sessions_created, second.sessions_updated) == (1, 0, 1)
        with team_scope(self.team.id):
            sessions = list(ResearchSession.objects.all())
        assert len(sessions) == 1
        assert sessions[0].status == SessionStatus.CANCELLED
        assert sessions[0].external_domains == ["example.com"]
