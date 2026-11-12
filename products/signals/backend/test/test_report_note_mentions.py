import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, User
from posthog.models.integration import Integration

from products.access_control.backend.models.role import Role, RoleMembership
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import NoteArtefact
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalUserAutonomyConfig
from products.signals.backend.report_access import may_read_reports
from products.signals.backend.report_note_mentions import (
    NoteMentions,
    deliver_note_mentions,
    notification_title,
    parse_note_mentions,
    render_note_text,
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

    def _note(self, text: str) -> SignalReportArtefact:
        return SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=NoteArtefact(note=text),
            attribution=ArtefactAttribution.from_user(self.user.id),
        )

    def _deliver(self, text: str) -> list[int]:
        artefact = self._note(text)
        with self.captureOnCommitCallbacks(execute=True):
            recipients = deliver_note_mentions(
                team_id=self.team.id,
                artefact_id=str(artefact.id),
                author_id=self.user.id,
                mentions=parse_note_mentions(text),
            )
        return [recipient.user.id for recipient in recipients]

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

    def test_leaves_out_people_without_inbox_access(self) -> None:
        def readable(*, user: User, team: object) -> bool:
            return user.id != self.mentioned.id and may_read_reports(user=user, team=team)  # type: ignore[arg-type]

        with patch("products.signals.backend.report_note_mentions.may_read_reports", side_effect=readable):
            recipient_ids = self._deliver(f"@member:{self.mentioned.id} @member:{self.role_member.id}")

        assert recipient_ids == [self.role_member.id]

    def test_a_failed_channel_does_not_stop_the_others(self) -> None:
        self.mocks["in_app"].side_effect = RuntimeError("notifications down")

        self._deliver(f"@member:{self.mentioned.id}")

        assert [call.args[0] for call in self.mocks["push"].call_args_list] == [self.mentioned.id]
        self.mocks["email"].return_value.send.assert_called_once()

    @parameterized.expand([("flag_off",), ("deleted_report",), ("only_the_author",)])
    def test_sends_nothing(self, case: str) -> None:
        text = f"@member:{self.mentioned.id}"
        if case == "flag_off":
            self.mocks["flag"].return_value = False
        elif case == "deleted_report":
            self.report.status = SignalReport.Status.DELETED
            self.report.save()
        else:
            text = f"@member:{self.user.id}"

        assert self._deliver(text) == []
        self.mocks["in_app"].assert_not_called()
        self.mocks["email"].assert_not_called()
        self.mocks["push"].assert_not_called()
