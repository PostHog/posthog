from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.models.scoping import team_scope
from posthog.test.persons import create_person

from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.models.util import insert_static_cohort
from products.research_desk.backend.facade import api, contracts
from products.research_desk.backend.facade.enums import SessionOrigin, SessionStatus, SourceKind, TouchChannel
from products.research_desk.backend.logic.emails import normalize_emails

PRODUCT_DATABASES = {"default", "research_desk_db_writer", "research_desk_db_reader"}
RESEARCH_WORKFLOW_ID = "wf-research"
MARKETING_WORKFLOW_ID = "wf-marketing"


class TestNormalizeEmails(SimpleTestCase):
    def test_strips_display_names_case_and_duplicates(self) -> None:
        assert normalize_emails(["Ada Lovelace <Ada@Example.com>", "ada@example.com ", "not-an-email"]) == [
            "ada@example.com"
        ]


class TestContactCheck(ClickhouseTestMixin, APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        create_person(team=self.team, distinct_ids=["ada"], properties={"email": "ada@example.com"})
        create_person(team=self.team, distinct_ids=["lookalike"], properties={"email": "bob@notexample.com"})
        with team_scope(self.team.id):
            self.workflow_source = api.create_source(
                contracts.CreateResearchSourceInput(
                    team_id=self.team.id,
                    kind=SourceKind.WORKFLOW,
                    external_id=RESEARCH_WORKFLOW_ID,
                    label="Replay interview outreach",
                    owner_email="researcher@posthog.com",
                )
            )

    def _send_email(self, distinct_id: str, email: str, workflow_id: str, days_ago: int) -> None:
        _create_event(
            team=self.team,
            event="$workflows_email_sent",
            distinct_id=distinct_id,
            properties={"$workflow_id": workflow_id, "$email_to": email},
            timestamp=self.now - timedelta(days=days_ago),
        )
        flush_persons_and_events()

    def _check(self, emails: tuple[str, ...] = (), domain: str | None = None) -> contracts.ContactCheckResult:
        with team_scope(self.team.id):
            return api.check_contact(contracts.ContactCheckInput(team_id=self.team.id, emails=emails, domain=domain))

    @parameterized.expand(
        [
            ("recent_research_email", RESEARCH_WORKFLOW_ID, 5, 1, True),
            ("old_research_email", RESEARCH_WORKFLOW_ID, 90, 1, False),
            ("marketing_email_is_not_research", MARKETING_WORKFLOW_ID, 5, 0, False),
        ]
    )
    def test_workflow_sends(
        self, _name: str, workflow_id: str, days_ago: int, expected_touches: int, expected_recent: bool
    ) -> None:
        self._send_email("ada", "ada@example.com", workflow_id, days_ago)

        result = self._check(emails=("Ada@Example.com",))

        assert len(result.touches) == expected_touches
        assert result.recently_contacted is expected_recent
        if expected_touches:
            assert result.touches[0].channel == TouchChannel.EMAIL
            assert result.touches[0].source_label == "Replay interview outreach"
            assert result.touches[0].owner_email == "researcher@posthog.com"

    def test_domain_matches_whole_domain_only(self) -> None:
        self._send_email("ada", "ada@example.com", RESEARCH_WORKFLOW_ID, 5)
        self._send_email("lookalike", "bob@notexample.com", RESEARCH_WORKFLOW_ID, 5)

        result = self._check(domain="@Example.com")

        assert [t.contact for t in result.touches] == ["ada@example.com"]

    def test_inactive_source_is_ignored(self) -> None:
        self._send_email("ada", "ada@example.com", RESEARCH_WORKFLOW_ID, 5)
        with team_scope(self.team.id):
            api.update_source(self.team.id, self.workflow_source.id, contracts.UpdateResearchSourceInput(active=False))

        assert self._check(emails=("ada@example.com",)).touches == []

    def test_event_and_survey_sources(self) -> None:
        with team_scope(self.team.id):
            api.create_source(
                contracts.CreateResearchSourceInput(
                    team_id=self.team.id,
                    kind=SourceKind.EVENT,
                    external_id="mcp interview invitation sent",
                    label="MCP",
                )
            )
            api.create_source(
                contracts.CreateResearchSourceInput(
                    team_id=self.team.id, kind=SourceKind.SURVEY, external_id="survey-1", label="Popover"
                )
            )
        _create_event(team=self.team, event="mcp interview invitation sent", distinct_id="ada", timestamp=self.now)
        _create_event(
            team=self.team,
            event="survey shown",
            distinct_id="ada",
            properties={"$survey_id": "survey-1"},
            timestamp=self.now,
        )
        _create_event(
            team=self.team,
            event="survey shown",
            distinct_id="ada",
            properties={"$survey_id": "other"},
            timestamp=self.now,
        )
        flush_persons_and_events()

        result = self._check(emails=("ada@example.com",))

        assert sorted(t.channel for t in result.touches) == [TouchChannel.EVENT, TouchChannel.SURVEY]

    def test_cohort_membership_warns_without_a_date(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Already interviewed", is_static=True)
        eve = create_person(team=self.team, distinct_ids=["eve"], properties={"email": "eve@example.com"})
        insert_static_cohort([eve.uuid], cohort.pk, team_id=self.team.pk)
        with team_scope(self.team.id):
            api.create_source(
                contracts.CreateResearchSourceInput(
                    team_id=self.team.id, kind=SourceKind.COHORT, external_id=str(cohort.id), label="Interviewed"
                )
            )

        result = self._check(emails=("eve@example.com", "ada@example.com"))

        assert [(t.channel, t.contact, t.occurred_at) for t in result.touches] == [
            (TouchChannel.COHORT, "eve@example.com", None)
        ]
        assert result.recently_contacted is True

    def test_sessions_match_by_email_and_domain_and_skip_cancelled(self) -> None:
        with team_scope(self.team.id):
            for ref, status in [("held", SessionStatus.HELD), ("cancelled", SessionStatus.CANCELLED)]:
                api.upsert_session(
                    contracts.UpsertResearchSessionInput(
                        team_id=self.team.id,
                        origin=SessionOrigin.CALENDAR,
                        external_ref=ref,
                        start_time=self.now - timedelta(days=3),
                        status=status,
                        title=f"Interview {ref}",
                        external_emails=("Carol <carol@example.com>",),
                    )
                )

        by_email = self._check(emails=("carol@example.com",))
        by_domain = self._check(domain="example.com")

        assert [t.source_label for t in by_email.touches] == ["Interview held"]
        assert [t.source_label for t in by_domain.touches] == ["Interview held"]
        assert by_email.recently_contacted is True

    @patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
    def test_contact_check_endpoint(self, _flag) -> None:
        self._send_email("ada", "ada@example.com", RESEARCH_WORKFLOW_ID, 5)
        url = f"/api/projects/{self.team.id}/research_desk/contact_check/"

        missing = self.client.get(url)
        found = self.client.get(url, {"emails": "nobody@example.org,ada@example.com"})

        assert missing.status_code == 400
        assert found.status_code == 200, found.json()
        assert found.json()["recently_contacted"] is True
        assert found.json()["touches"][0]["channel"] == "email"
