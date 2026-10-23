import json
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized

from posthog.llm.system_one import ChoiceAnswer, RefusalAnswer, SystemOneResult
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.logic.feature_tips import catalog, interactivity, offer, picker
from products.slack_app.backend.logic.feature_tips.catalog import CATALOG
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.offer import TipRequest, offer_feature_tip
from products.slack_app.backend.logic.feature_tips.state import get_state, parse_state
from products.slack_app.backend.models import SlackSettings, SlackThreadTaskMapping, UntaggedFollowupMode

WORKSPACE = "T_TIPS"
SLACK_USER = "U_READER"


@pytest.mark.django_db
class TestOfferFeatureTip:
    @pytest.fixture(autouse=True)
    def setup(self):
        organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=organization, name="Team")
        # No linked PostHog user and no optional scopes, so the thread follow-up tip ranks first.
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id=WORKSPACE, sensitive_config={"access_token": "xoxb-test"}
        )
        with (
            patch.object(offer, "is_slack_app_feature_tips_enabled", return_value=True) as self.flag,
            patch.object(offer, "post_slack_ephemeral") as self.post,
            patch.object(offer, "SlackIntegration"),
            patch.object(catalog, "is_slack_app_unprompted_answers_enabled", return_value=False),
            # The decision model is not reachable here, so every pick falls back to the ranked order.
            patch.object(picker, "build_system_one_client", side_effect=RuntimeError("no gateway")),
        ):
            yield

    def _threads(self, count: int) -> None:
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        for index in range(count):
            task = Task.objects.create(team=self.team, title="t")
            SlackThreadTaskMapping.objects.create(
                team=self.team,
                integration=self.integration,
                slack_workspace_id=WORKSPACE,
                channel="C1",
                thread_ts=f"{index}.1",
                task=task,
                task_run=TaskRun.objects.create(team=self.team, task=task),
                mentioning_slack_user_id=SLACK_USER,
            )

    def _offer(self) -> SlackFeature | None:
        return offer_feature_tip(
            TipRequest(
                integration=self.integration,
                slack_user_id=SLACK_USER,
                posthog_user=None,
                channel="C1",
                thread_ts="1.1",
                person_message="how many signups last week?",
            )
        )

    def test_existing_user_gets_a_tip_at_the_first_answer_after_launch(self):
        self._threads(3)

        assert self._offer() == SlackFeature.THREAD_FOLLOWUP
        self.post.assert_called_once()
        assert get_state(WORKSPACE, SLACK_USER).shown[SlackFeature.THREAD_FOLLOWUP.value].times_shown == 1

    def test_new_user_gets_no_tip_before_the_third_interaction(self):
        self._threads(1)

        assert [self._offer(), self._offer(), self._offer()] == [None, None, SlackFeature.THREAD_FOLLOWUP]

    def test_at_most_one_tip_a_day_and_each_tip_only_once(self):
        self._threads(3)
        assert self._offer() == SlackFeature.THREAD_FOLLOWUP

        assert self._offer() is None
        state = get_state(WORKSPACE, SLACK_USER)
        state.last_shown_at = timezone.now() - timedelta(days=2)
        SlackSettings.objects.filter(slack_workspace_id=WORKSPACE, slack_user_id=SLACK_USER).update(
            feature_tips=state.model_dump(mode="json")
        )
        second = self._offer()
        assert second is not None and second != SlackFeature.THREAD_FOLLOWUP
        assert self.post.call_count == 2

    @parameterized.expand(
        [
            ("opted out", {"opted_out_at": "2026-01-01T00:00:00Z"}, None, None),
            (
                "chose a follow-up mode before tips existed",
                {},
                UntaggedFollowupMode.NEVER,
                SlackFeature.FILE_ATTACHMENTS,
            ),
            (
                "used a feature that leaves no setting",
                {"used": {"file_attachments": "2026-01-01T00:00:00Z"}},
                UntaggedFollowupMode.NEVER,
                SlackFeature.MODEL_IN_MENTION,
            ),
        ]
    )
    def test_skips_what_the_reader_turned_off_or_already_uses(self, _name, stored_state, followup_mode, expected):
        self._threads(3)
        SlackSettings.objects.create(
            slack_workspace_id=WORKSPACE,
            slack_user_id=SLACK_USER,
            untagged_followup_mode=followup_mode,
            feature_tips={"backfilled_at": "2026-01-01T00:00:00Z", "interaction_count": 5, **stored_state},
        )

        assert self._offer() == expected

    def test_flag_off_writes_nothing(self):
        self._threads(3)
        self.flag.return_value = False

        assert self._offer() is None
        assert not SlackSettings.objects.filter(slack_workspace_id=WORKSPACE, slack_user_id=SLACK_USER).exists()


class TestCatalog(SimpleTestCase):
    def test_every_feature_has_a_tip_and_a_unique_rank(self):
        assert set(CATALOG) == set(SlackFeature)
        assert len({tip.rank for tip in CATALOG.values()}) == len(CATALOG)
        assert all(tip.emoji and tip.title for tip in CATALOG.values())


class TestInboxChannelTarget(SimpleTestCase):
    @parameterized.expand(
        [
            (SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL, "C1|#posthog-inbox"),
            (SlackThreadTaskMapping.ConversationType.PRIVATE_CHANNEL, None),
            (SlackThreadTaskMapping.ConversationType.UNKNOWN, None),
        ]
    )
    def test_only_a_public_inbox_channel_is_named_in_a_tip(self, conversation_type, expected):
        ctx = catalog.TipContext(
            integration=MagicMock(team_id=1),
            slack_user_id=SLACK_USER,
            posthog_user_id=None,
            channel="C2",
            settings=MagicMock(),
        )
        with (
            patch.object(catalog, "has_inbox_scopes", return_value=True),
            patch.object(catalog, "_get_team_channel", return_value="C1|#posthog-inbox"),
            patch.object(catalog, "SlackIntegration"),
            patch.object(catalog, "resolve_conversation_type", return_value=conversation_type),
        ):
            assert ctx.inbox_channel_target == expected


class TestInboxChannelJoin(SimpleTestCase):
    @parameterized.expand(
        [
            (SlackThreadTaskMapping.ConversationType.PUBLIC_CHANNEL, True),
            (SlackThreadTaskMapping.ConversationType.PRIVATE_CHANNEL, False),
        ]
    )
    def test_join_rechecks_that_the_channel_is_still_public(self, conversation_type, invited):
        with (
            patch.object(catalog, "ensure_inbox_channel", return_value=("C1", "#posthog-inbox")),
            patch.object(catalog, "SlackIntegration"),
            patch.object(catalog, "resolve_conversation_type", return_value=conversation_type),
            patch.object(catalog, "invite_user_to_inbox", return_value=True) as invite,
        ):
            CATALOG[SlackFeature.INBOX_CHANNEL].apply_action(MagicMock(), SLACK_USER)

        assert invite.called is invited


class TestChooseTip(SimpleTestCase):
    candidates = [CATALOG[SlackFeature.SUBSCRIPTION], CATALOG[SlackFeature.CODE_CHANGE_PR]]

    @parameterized.expand(
        [
            (
                "confident match",
                ChoiceAnswer(choice="code_change_pr", confidence=0.9, probabilities={}),
                "code_change_pr",
                "contextual",
            ),
            (
                "low confidence",
                ChoiceAnswer(choice="code_change_pr", confidence=0.3, probabilities={}),
                "subscription",
                "ranked",
            ),
            ("no match", ChoiceAnswer(choice="none", confidence=0.95, probabilities={}), "subscription", "ranked"),
            (
                "not a candidate",
                ChoiceAnswer(choice="mcp_tool", confidence=0.95, probabilities={}),
                "subscription",
                "ranked",
            ),
            ("refusal", RefusalAnswer(), "subscription", "ranked"),
        ]
    )
    def test_the_model_orders_but_never_blocks(self, _name, answer, expected_feature, expected_source):
        client = MagicMock()
        client.decide.return_value = SystemOneResult(
            model="jev", answers={picker.FEATURE_TIP_QUESTION_ID: answer}, input_tokens=None
        )
        with patch.object(picker, "build_system_one_client", return_value=client):
            choice = picker.choose_tip(self.candidates, "fix the checkout error", team_id=1, distinct_id=None)

        assert choice is not None
        assert (choice.feature.value, choice.source) == (expected_feature, expected_source)

    def test_an_outage_falls_back_to_the_ranked_tip(self):
        with patch.object(picker, "build_system_one_client", side_effect=RuntimeError("gateway down")):
            choice = picker.choose_tip(self.candidates, "fix the checkout error", team_id=1, distinct_id=None)

        assert choice is not None
        assert (choice.feature, choice.source) == (SlackFeature.SUBSCRIPTION, "ranked")


@pytest.mark.django_db
class TestFeatureTipClicks:
    @pytest.fixture(autouse=True)
    def setup(self):
        organization = Organization.objects.create(name="Org")
        team = Team.objects.create(organization=organization, name="Team")
        self.integration = Integration.objects.create(
            team=team, kind="slack", integration_id=WORKSPACE, sensitive_config={"access_token": "xoxb-test"}
        )
        with patch.object(interactivity, "post_response_url") as self.respond:
            yield

    def _click(self, action_id: str, feature: str, slack_team_id: str = WORKSPACE) -> None:
        interactivity.handle_feature_tip_action(
            {
                "user": {"id": SLACK_USER},
                "team": {"id": slack_team_id},
                "response_url": "https://hooks.slack.com/actions/x",
                "actions": [
                    {
                        "action_id": action_id,
                        "value": json.dumps({"integration_id": self.integration.id, "feature": feature}),
                    }
                ],
            }
        )

    def _settings(self) -> SlackSettings | None:
        return SlackSettings.objects.filter(slack_workspace_id=WORKSPACE, slack_user_id=SLACK_USER).first()

    @parameterized.expand(
        [
            (SlackFeature.THREAD_FOLLOWUP, "untagged_followup_mode", UntaggedFollowupMode.AUTO),
            (SlackFeature.AUTO_MODEL_CHOICE, "auto_model_choice", True),
            (SlackFeature.UNPROMPTED_ANSWERS, "untagged_question_mode", UntaggedFollowupMode.AUTO),
        ]
    )
    def test_action_cta_turns_the_setting_on(self, feature, column, expected):
        self._click(offer.FEATURE_TIP_CTA_ACTION_ID, feature.value)

        settings = self._settings()
        assert settings is not None
        assert getattr(settings, column) == expected
        assert feature.value in parse_state(settings.feature_tips).used

    def test_opt_out_stops_all_tips(self):
        self._click(offer.FEATURE_TIP_OPT_OUT_ACTION_ID, SlackFeature.SUBSCRIPTION.value)

        assert get_state(WORKSPACE, SLACK_USER).opted_out_at is not None

    def test_a_click_from_another_workspace_changes_nothing(self):
        self._click(offer.FEATURE_TIP_OPT_OUT_ACTION_ID, SlackFeature.SUBSCRIPTION.value, slack_team_id="T_OTHER")

        assert self._settings() is None
        self.respond.assert_called_once_with("https://hooks.slack.com/actions/x", {"delete_original": True})
