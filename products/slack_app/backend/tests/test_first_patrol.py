import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.signals.backend.facade.api import ScoutRunDigest
from products.slack_app.backend import first_patrol

COLLECT_PATH = "products.signals.backend.facade.api.collect_scout_run_digests"
CAPTURE_PATH = "products.slack_app.backend.first_patrol.capture_slack_event"
WEBCLIENT = "posthog.models.integration.WebClient"
WORKSPACE = "T1"
SLACK_USER = "U1"
DM_CHANNEL = "D1"


def _collect(digests):
    with patch(COLLECT_PATH, return_value=digests):
        return first_patrol.collect_first_patrol_digest(
            team_id=1, channel_name="posthog-inbox", scout_config_ids=["c1"], provisioned_at_iso="2026-07-02T00:00:00"
        )


class TestFirstPatrolDigestComposition:
    @parameterized.expand(
        [
            ("no_completed_runs", None),
            (
                "clean_patrol",
                [
                    ScoutRunDigest(
                        skill_name="signals-scout-slack-csm-account-pulse",
                        summary="Checked 214 accounts, all within baseline.",
                        notifications_sent=0,
                        reports_filed=0,
                    ),
                    ScoutRunDigest(
                        skill_name="signals-scout-slack-csm-revenue-watch",
                        summary="",
                        notifications_sent=0,
                        reports_filed=0,
                    ),
                ],
            ),
        ]
    )
    def test_returns_none_so_no_dm_is_sent(self, _name, digests):
        assert _collect(digests) is None

    def test_finding_variant_leads_with_the_finding_and_links_channel(self):
        digest = _collect(
            [
                ScoutRunDigest(
                    skill_name="signals-scout-slack-csm-account-pulse",
                    summary="Initech's weekly active users dropped 60% vs baseline. Fleet otherwise steady.",
                    notifications_sent=1,
                    reports_filed=1,
                ),
                ScoutRunDigest(
                    skill_name="signals-scout-slack-csm-support-watch",
                    summary="Queue quiet.",
                    notifications_sent=0,
                    reports_filed=0,
                ),
            ]
        )
        assert digest["variant"] == "finding"
        assert "Account pulse" in digest["text"]
        assert "Initech's weekly active users dropped 60% vs baseline." in digest["text"]
        assert "#posthog-inbox" in digest["text"]
        assert digest["runs_completed"] == 2

    def test_long_finding_headline_has_no_doubled_punctuation(self):
        long_summary = "The account " + "very " * 60 + "quietly slid this week."
        digest = _collect(
            [
                ScoutRunDigest(
                    skill_name="signals-scout-slack-csm-account-pulse",
                    summary=long_summary,
                    notifications_sent=1,
                    reports_filed=1,
                )
            ]
        )
        assert "…." not in digest["text"]
        assert "…" in digest["text"]

    def test_multiple_finders_counted_beyond_the_headline(self):
        digest = _collect(
            [
                ScoutRunDigest(
                    skill_name="signals-scout-slack-csm-account-pulse",
                    summary="A slid.",
                    notifications_sent=1,
                    reports_filed=1,
                ),
                ScoutRunDigest(
                    skill_name="signals-scout-slack-csm-support-watch",
                    summary="B spiked.",
                    notifications_sent=1,
                    reports_filed=1,
                ),
            ]
        )
        assert digest["variant"] == "finding"
        assert "1 more scout reported findings too" in digest["text"]


class TestPostFirstPatrolDigest:
    # The digest DM is the onboarding funnel's final step. Nothing else asserts the emitted
    # identity — the composition tests stop at collect, and the workflow test mocks this post —
    # so an arg-swap or a fallback to capture_slack_event's team-uuid default would silently
    # detach the digest from per-user funnel chaining.
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.organization, name="Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=WORKSPACE,
            config={"scope": "chat:write"},
            sensitive_config={"access_token": "xoxb-test"},
        )

    @patch(CAPTURE_PATH)
    @patch(WEBCLIENT)
    def test_dm_posts_and_pins_event_to_the_per_user_person(self, mock_webclient, mock_capture):
        digest = {"text": "Your scouts found something.", "variant": "finding", "runs_completed": 2}

        first_patrol.post_first_patrol_digest(
            integration_id=self.integration.id,
            slack_user_id=SLACK_USER,
            dm_channel_id=DM_CHANNEL,
            thread_ts="111.222",
            digest=digest,
        )

        mock_webclient.return_value.chat_postMessage.assert_called_once_with(
            channel=DM_CHANNEL, thread_ts="111.222", text=digest["text"]
        )
        mock_capture.assert_called_once()
        assert mock_capture.call_args.args[1] == first_patrol.EVENT_DIGEST_SENT
        assert mock_capture.call_args.kwargs["distinct_id"] == first_patrol.slack_user_distinct_id(
            self.integration.integration_id, SLACK_USER
        )
        assert mock_capture.call_args.kwargs["persona"] == first_patrol.PERSONA_CSM

    @patch(CAPTURE_PATH)
    @patch(WEBCLIENT)
    def test_missing_integration_is_a_silent_no_op(self, mock_webclient, mock_capture):
        first_patrol.post_first_patrol_digest(
            integration_id=self.integration.id + 999,
            slack_user_id=SLACK_USER,
            dm_channel_id=DM_CHANNEL,
            thread_ts=None,
            digest={"text": "unused", "variant": "finding", "runs_completed": 1},
        )

        mock_webclient.assert_not_called()
        mock_capture.assert_not_called()
