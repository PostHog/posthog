import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.models.scoping import team_scope

from products.research_desk.backend.facade import api, contracts
from products.research_desk.backend.facade.enums import SessionOrigin, SessionStatus, TouchChannel
from products.research_desk.backend.logic.briefs import NO_TOUCHES_TEXT, compose_brief, contact_checks_for
from products.research_desk.backend.models import ResearchSession

PRODUCT_DATABASES = {"default", "research_desk_db_writer", "research_desk_db_reader"}
POST_WITH_JOIN = "products.research_desk.backend.logic.brief_posting.post_with_join"
NOW = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)


def _session_dto(**overrides: Any) -> contracts.ResearchSessionDTO:
    values: dict[str, Any] = {
        "id": uuid4(),
        "origin": SessionOrigin.CALENDAR,
        "external_ref": "evt-1",
        "title": "Replay interview",
        "start_time": NOW + timedelta(hours=3),
        "end_time": None,
        "status": SessionStatus.SCHEDULED,
        "organizer_email": "organizer@posthog.com",
        "internal_emails": [],
        "external_emails": ["ada@example.com", "bob@gmail.com"],
        "meeting_url": "https://meet.example.com/abc",
        "brief_posted_at": None,
        "created_at": NOW,
    }
    return contracts.ResearchSessionDTO(**{**values, **overrides})


def _check(touches: list[contracts.ResearchTouch]) -> contracts.ContactCheckResult:
    return contracts.ContactCheckResult(
        emails=[],
        domain=None,
        touches=touches,
        last_touch_at=None,
        recently_contacted=bool(touches),
        warn_within_days=60,
        lookback_days=180,
    )


class TestComposeBrief(SimpleTestCase):
    def test_checks_skip_personal_email_domains(self) -> None:
        checks = contact_checks_for(_session_dto(), team_id=1)

        assert [(c.emails, c.domain) for c in checks] == [
            (("ada@example.com", "bob@gmail.com"), None),
            ((), "example.com"),
        ]

    @parameterized.expand([("with_prior_touches", True), ("without_prior_touches", False)])
    def test_lists_prior_touches(self, _name: str, has_prior_touch: bool) -> None:
        session = _session_dto()
        prior = contracts.ResearchTouch(
            channel=TouchChannel.EMAIL,
            contact="ada@example.com",
            source_label="Error tracking outreach",
            owner_email="researcher@posthog.com",
            occurred_at=NOW - timedelta(days=12),
        )
        own_session = contracts.ResearchTouch(
            channel=TouchChannel.SESSION,
            contact="ada@example.com",
            source_label=session.title,
            owner_email=session.organizer_email,
            occurred_at=session.start_time,
            session_id=session.id,
        )
        touches = [prior, own_session] if has_prior_touch else [own_session]
        brief = compose_brief(session, [_check(touches), _check(touches)], followup_invite="Ask @PostHog")

        rendered = json.dumps(brief.blocks)
        touches_text = brief.blocks[3]["text"]["text"]
        if has_prior_touch:
            assert touches_text.count("ada@example.com") == 1
            assert "researcher@posthog.com" in touches_text
            assert "Error tracking outreach" in touches_text
        else:
            assert NO_TOUCHES_TEXT in touches_text
        assert brief.blocks[2]["accessory"]["url"] == "https://meet.example.com/abc"
        assert brief.blocks[-1] == {"type": "context", "elements": [{"type": "mrkdwn", "text": "Ask @PostHog"}]}
        assert f"<!date^{int(session.start_time.timestamp())}^" in rendered


class TestPostDueBriefs(APIBaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.now = timezone.now()
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", config={}, sensitive_config={"access_token": "xoxb-test"}
        )
        self.configured = override_settings(
            RESEARCH_DESK_TEAM_ID=self.team.id,
            RESEARCH_DESK_SLACK_INTEGRATION_ID=self.integration.id,
            RESEARCH_DESK_SLACK_CHANNEL_ID="C0TEST",
        )

    def _session(self, ref: str, hours_from_now: float, status: SessionStatus = SessionStatus.SCHEDULED) -> str:
        with team_scope(self.team.id):
            session, _ = api.upsert_session(
                contracts.UpsertResearchSessionInput(
                    team_id=self.team.id,
                    origin=SessionOrigin.CALENDAR,
                    external_ref=ref,
                    start_time=self.now + timedelta(hours=hours_from_now),
                    status=status,
                    title=f"Interview {ref}",
                    external_emails=("ada@example.com",),
                )
            )
        return str(session.id)

    def _row(self, session_id: str) -> ResearchSession:
        return ResearchSession.all_teams.get(id=session_id)

    @patch(POST_WITH_JOIN, return_value="1700000000.000100")
    def test_posts_each_due_session_once(self, post: MagicMock) -> None:
        due = self._session("due", 2)
        skipped = [
            self._session("started", -1),
            self._session("later", 30),
            self._session("cancelled", 2, SessionStatus.CANCELLED),
            self._session("briefed", 2),
        ]
        ResearchSession.all_teams.filter(id=skipped[-1]).update(brief_posted_at=self.now)

        with self.configured:
            assert api.post_due_briefs() == 1
            assert api.post_due_briefs() == 0

        assert post.call_count == 1
        assert post.call_args.args[1] == "C0TEST"
        assert "Interview due" in post.call_args.args[3]
        assert self._row(due).slack_message_ts == "1700000000.000100"
        assert self._row(due).brief_posted_at is not None
        assert [self._row(s).slack_message_ts for s in skipped] == ["", "", "", ""]

    @patch(POST_WITH_JOIN)
    def test_failed_post_is_retried_next_run(self, post: MagicMock) -> None:
        due = self._session("due", 2)
        post.side_effect = [SlackApiError("boom", {"error": "ratelimited"}), "1700000000.000200"]

        with self.configured:
            assert api.post_due_briefs() == 0
            assert self._row(due).brief_posted_at is None
            assert api.post_due_briefs() == 1

        assert self._row(due).slack_message_ts == "1700000000.000200"

    @parameterized.expand(
        [
            ("no_team", {"RESEARCH_DESK_TEAM_ID": None}),
            ("no_integration", {"RESEARCH_DESK_SLACK_INTEGRATION_ID": None}),
            ("no_channel", {"RESEARCH_DESK_SLACK_CHANNEL_ID": ""}),
        ]
    )
    @patch(POST_WITH_JOIN)
    def test_noop_until_configured(self, _name: str, missing: dict[str, Any], post: MagicMock) -> None:
        self._session("due", 2)

        with self.configured, override_settings(**missing):
            assert api.post_due_briefs() == 0

        post.assert_not_called()
