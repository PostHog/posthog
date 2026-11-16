import uuid

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers
from slack_sdk.errors import SlackApiError

from posthog.constants import AvailableFeature
from posthog.models import Organization, User
from posthog.models.integration import Integration
from posthog.token_bucket import Budget, consume

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.role import Role, RoleMembership
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_note_mentions import (
    NoteMentions,
    deliver_note_mentions,
    notification_title,
    parse_note_mentions,
    render_note_text,
    send_report_note_mention_slack,
)

ROLE_ID = uuid.UUID("0190f3a1-7d2e-7c41-9a3b-5e6f7a8b9c0d")


class TestNoteMentionText(SimpleTestCase):
    @parameterized.expand(
        [
            ("member", "@member:12 can you look", {12}, set()),
            ("role", f"cc @role:{ROLE_ID}", set(), {ROLE_ID}),
            ("both_and_repeats", f"@member:3 @member:3\n@role:{ROLE_ID}", {3}, {ROLE_ID}),
            ("glued_to_a_word", "foo@member:12 and x@role:" + str(ROLE_ID), set(), set()),
            ("email_address", "write to dylan@example.com", set(), set()),
            ("role_with_a_number_id", "@role:12", set(), set()),
            ("member_id_too_long_to_convert", "@member:" + "9" * 4301, set(), set()),
        ]
    )
    def test_parse_note_mentions(self, _name: str, text: str, user_ids: set[int], role_ids: set[uuid.UUID]) -> None:
        assert parse_note_mentions(text) == NoteMentions(user_ids=frozenset(user_ids), role_ids=frozenset(role_ids))

    def test_render_note_text_names_every_token(self) -> None:
        text = f"@member:1 and @member:2, see @role:{ROLE_ID}"
        rendered = render_note_text(text, names_by_user_id={1: "Dylan"}, names_by_role_id={ROLE_ID: "Self-driving"})
        assert rendered == "@Dylan and @someone, see @Self-driving"

    def test_notification_title_fits_the_column(self) -> None:
        title = notification_title(author_name="x" * 400, role_name="y" * 40)
        assert len(title) <= 255
        assert title.endswith(" mentioned @" + "y" * 40 + " on a report")


class TestDeliverNoteMentions(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.first_name = "Andy"
        self.user.save()
        self.mentioned = User.objects.create_and_join(self.organization, "dylan@example.com", None, first_name="Dylan")
        self.role_member = User.objects.create_and_join(self.organization, "sam@example.com", None, first_name="Sam")
        other_organization = Organization.objects.create(name="Other")
        self.outsider = User.objects.create_and_join(other_organization, "out@example.com", None, first_name="Out")
        self.role = Role.objects.create(name="Self-driving", organization=self.organization)
        for user in (self.role_member, self.user):
            RoleMembership.objects.create(role=self.role, user=user)
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Checkout fails", summary="Summary"
        )

        patches = {
            "flag": patch("posthoganalytics.feature_enabled", return_value=True),
            "in_app": patch("products.signals.backend.report_note_mentions.create_notification"),
            "email_available": patch(
                "products.signals.backend.report_note_mentions.is_email_available", return_value=True
            ),
            "email": patch("products.signals.backend.report_note_mentions.EmailMessage"),
            "push": patch("products.signals.backend.inbox_push_notifications.send_user_push.delay"),
            "slack": patch("products.signals.backend.slack_inbox_notifications.SlackIntegration"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        self.slack_dispatches: list[dict] = []
        self.run_slack_now = True
        slack_task = patch.object(send_report_note_mention_slack, "apply_async", side_effect=self._dispatch_slack)
        slack_task.start()
        self.addCleanup(slack_task.stop)

    def _dispatch_slack(self, *, kwargs: dict, countdown: int = 0) -> None:
        self.slack_dispatches.append({**kwargs, "countdown": countdown})
        # The first attempt runs here, as a worker would. A delayed retry is only recorded.
        if self.run_slack_now and countdown == 0:
            send_report_note_mention_slack(**kwargs)

    def _note(self, text: str, **content: object) -> SignalReportArtefact:
        return SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=NoteArtefact(note=text, **content),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )

    def _deliver_artefact(self, artefact: SignalReportArtefact, mentions: NoteMentions) -> list[int]:
        with self.captureOnCommitCallbacks(execute=True):
            recipients = deliver_note_mentions(
                team_id=self.team.id, artefact_id=str(artefact.id), author_id=self.user.id, mentions=mentions
            )
        return [recipient.user.id for recipient in recipients]

    def _deliver(self, text: str) -> list[int]:
        return self._deliver_artefact(self._note(text), parse_note_mentions(text))

    def _inbox_slack_workspace(self) -> Integration:
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T123", config={}, sensitive_config={"access_token": "x"}
        )
        SignalTeamConfig.objects.update_or_create(
            team=self.team,
            defaults={
                "default_slack_notification_integration_id": integration.id,
                "default_slack_notification_channel": "C0INBOX|#inbox",
            },
        )
        return integration

    def test_notifies_mentioned_people_and_role_members_on_every_channel(self) -> None:
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T123", config={}, sensitive_config={"access_token": "x"}
        )
        SignalUserAutonomyConfig.objects.create(
            user=self.mentioned, slack_notification_integration=integration, slack_notification_channel="U0DYLAN|@dylan"
        )

        recipient_ids = self._deliver(
            f"@member:{self.mentioned.id} @member:{self.outsider.id} and @role:{self.role.id} can you look"
        )

        assert recipient_ids == [self.mentioned.id, self.role_member.id]
        in_app = {call.args[0].target_id: call.args[0] for call in self.mocks["in_app"].call_args_list}
        assert set(in_app) == {str(self.mentioned.id), str(self.role_member.id)}
        assert in_app[str(self.mentioned.id)].title == "Andy mentioned you on a report"
        assert in_app[str(self.role_member.id)].title == "Andy mentioned @Self-driving on a report"
        assert in_app[str(self.mentioned.id)].body == "@Dylan @someone and @Self-driving can you look"
        assert in_app[str(self.mentioned.id)].resource_type == "inbox"
        assert in_app[str(self.mentioned.id)].source_url.startswith(
            f"/project/{self.team.id}/inbox/reports/{self.report.id}"
        )
        emailed = {call.args[0] for call in self.mocks["email"].return_value.add_user_recipient.call_args_list}
        assert emailed == {self.mentioned, self.role_member}
        pushed = {call.args[0] for call in self.mocks["push"].call_args_list}
        assert pushed == {self.mentioned.id, self.role_member.id}
        slack_posts = self.mocks["slack"].return_value.client.chat_postMessage.call_args_list
        assert [call.kwargs["channel"] for call in slack_posts] == ["U0DYLAN"]
        assert "mentioned you on" in slack_posts[0].kwargs["blocks"][0]["text"]["text"]

    @parameterized.expand([("no_inbox_access",), ("no_access_to_a_private_project",)])
    def test_leaves_out_people_who_may_not_read_the_report(self, case: str) -> None:
        def readable(*, user: User, team: object) -> bool:
            return user.id != self.mentioned.id and may_read_reports(user=user, team=team)  # type: ignore[arg-type]

        text = f"@member:{self.mentioned.id} @member:{self.role_member.id}"
        if case == "no_inbox_access":
            with patch("products.signals.backend.report_note_mentions.may_read_reports", side_effect=readable):
                recipient_ids = self._deliver(text)
        else:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )
            membership = self.role_member.organization_memberships.get(organization=self.organization)
            AccessControl.objects.create(
                team=self.team,
                resource="project",
                resource_id=str(self.team.id),
                organization_member=membership,
                access_level="member",
            )
            recipient_ids = self._deliver(text)

        assert recipient_ids == [self.role_member.id]
        self.mocks["slack"].return_value.client.chat_postMessage.assert_not_called()

    def test_a_failed_channel_does_not_stop_the_others(self) -> None:
        self.mocks["in_app"].side_effect = RuntimeError("notifications down")

        self._deliver(f"@member:{self.mentioned.id}")

        assert [call.args[0] for call in self.mocks["push"].call_args_list] == [self.mentioned.id]
        self.mocks["email"].return_value.send.assert_called_once()

    @parameterized.expand(
        [
            ("flag_off",),
            ("deleted_report",),
            ("only_the_author",),
            ("protected_assessment_note",),
            ("mention_removed_before_the_send",),
            ("author_out_of_send_budget",),
        ]
    )
    def test_sends_nothing(self, case: str) -> None:
        text = f"@member:{self.mentioned.id}"
        artefact: SignalReportArtefact | None = None
        if case == "flag_off":
            self.mocks["flag"].return_value = False
        elif case == "deleted_report":
            self.report.status = SignalReport.Status.DELETED
            self.report.save()
        elif case == "only_the_author":
            text = f"@member:{self.user.id}"
        elif case == "protected_assessment_note":
            artefact = self._note(text, analytics_query_context=[], restricted_to_user_id=self.user.id)
        elif case == "mention_removed_before_the_send":
            artefact = self._note("Never mind, this is handled.")
        else:
            budget = Budget(burst=1, per_hour=1)
            consume(f"signals_note_mentions:{self.team.id}:{self.user.id}", budget)
            self.enterContext(patch("products.signals.backend.report_note_mentions.MENTION_SEND_BUDGET", budget))

        recipient_ids = (
            self._deliver(text) if artefact is None else self._deliver_artefact(artefact, parse_note_mentions(text))
        )

        assert recipient_ids == []
        self.mocks["in_app"].assert_not_called()
        self.mocks["email"].assert_not_called()
        self.mocks["push"].assert_not_called()

    def test_a_later_edit_is_a_new_delivery(self) -> None:
        text = f"@member:{self.mentioned.id} can you look"
        artefact = self._note(text)
        self._deliver_artefact(artefact, parse_note_mentions(text))
        artefact.update_content({"note": text})
        self._deliver_artefact(artefact, parse_note_mentions(text))

        keys = [call.args[0].idempotency_key for call in self.mocks["in_app"].call_args_list]
        assert len(keys) == 2 and keys[0] != keys[1]

    def test_slack_keeps_names_and_note_text_literal(self) -> None:
        self.user.first_name = "<!channel>"
        self.user.save()
        integration = self._inbox_slack_workspace()
        SignalUserAutonomyConfig.objects.create(
            user=self.mentioned, slack_notification_integration=integration, slack_notification_channel="U0DYLAN|@dylan"
        )

        self._deliver(f"@member:{self.mentioned.id} @here please look")

        post = self.mocks["slack"].return_value.client.chat_postMessage.call_args.kwargs
        assert "<!channel>" not in post["text"]
        assert post["blocks"][0]["text"]["verbatim"] is True

    def test_slack_skips_a_member_who_is_no_longer_eligible(self) -> None:
        integration = self._inbox_slack_workspace()
        SignalUserAutonomyConfig.objects.create(
            user=self.mentioned, slack_notification_integration=integration, slack_notification_channel="U0DYLAN|@dylan"
        )
        self.mocks["slack"].return_value.get_user_by_id.return_value = None

        self._deliver(f"@member:{self.mentioned.id}")

        self.mocks["slack"].return_value.client.chat_postMessage.assert_not_called()

    def test_slack_runs_in_its_own_task(self) -> None:
        self.run_slack_now = False
        self._inbox_slack_workspace()

        with patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email", return_value="U0SOMEONE"
        ):
            recipient_ids = self._deliver(f"@member:{self.mentioned.id} @member:{self.role_member.id}")

        assert len(self.mocks["in_app"].call_args_list) == 2
        self.mocks["slack"].return_value.client.chat_postMessage.assert_not_called()
        assert [(d["only_user_ids"], d["attempt"], d["countdown"]) for d in self.slack_dispatches] == [
            (sorted(recipient_ids), 1, 0)
        ]

    @parameterized.expand([("member_lookup_budget", 60), ("slack_rate_limit", 30)])
    def test_slack_retries_the_people_it_could_not_reach(self, case: str, expected_countdown: int) -> None:
        self._inbox_slack_workspace()
        text = f"@member:{self.mentioned.id} @member:{self.role_member.id}"
        lookup = "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email"
        post = self.mocks["slack"].return_value.client.chat_postMessage
        if case == "member_lookup_budget":
            lookup_patch = patch(lookup, side_effect=serializers.ValidationError("budget"))
        else:
            lookup_patch = patch(lookup, return_value="U0SOMEONE")
            response = MagicMock(status_code=429, headers={"Retry-After": "30"})
            response.get.return_value = "ratelimited"
            post.side_effect = SlackApiError("ratelimited", response)

        with lookup_patch:
            self._deliver(text)

        retry = self.slack_dispatches[-1]
        assert (retry["only_user_ids"], retry["attempt"], retry["countdown"]) == (
            sorted([self.mentioned.id, self.role_member.id]),
            2,
            expected_countdown,
        )

        post.reset_mock(side_effect=True)
        with patch(lookup, return_value="U0SOMEONE"):
            send_report_note_mention_slack(**{k: v for k, v in retry.items() if k != "countdown"})

        assert post.call_count == 2
