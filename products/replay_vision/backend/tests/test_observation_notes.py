from posthog.test.base import APIBaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment, CommentSlackThread
from posthog.models.comment.utils import OBSERVATION_NOTE_PLACEHOLDER
from posthog.tasks.email import send_discussions_mentioned

from products.access_control.backend.models.access_control import AccessControl
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerModel, ScannerType
from products.replay_vision.backend.tests.helpers import snapshot_for

SCOPE = "ReplayObservation"


class TestObservationNotesAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        self.scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Checkout monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user check out?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        self.observation = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id="s-notes",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            completed_at=timezone.now(),
        )
        self.note = Comment.objects.create(
            team=self.team, scope=SCOPE, item_id=str(self.observation.id), content="private note", created_by=self.user
        )
        self.member = User.objects.create_and_join(self.organization, "notes-member@posthog.com", "password")

    def _set_member_scanner_access(self, access_level: str) -> None:
        self._set_member_access("replay_scanner", access_level, str(self.scanner.id))

    def _set_member_access(self, resource: str, access_level: str, resource_id: str | None = None) -> None:
        AccessControl.objects.create(
            team=self.team,
            resource=resource,
            resource_id=resource_id,
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            access_level=access_level,
        )

    @parameterized.expand(
        [
            ("scanner_denied", "replay_scanner", "none", False),
            ("recordings_denied", "session_recording", "none", False),
            ("scanner_viewer", "replay_scanner", "viewer", True),
        ]
    )
    def test_notes_follow_observation_access(self, _name: str, resource: str, access_level: str, allowed: bool) -> None:
        self._set_member_access(resource, access_level, str(self.scanner.id) if resource == "replay_scanner" else None)
        self.client.force_login(self.member)
        base = f"/api/projects/{self.team.id}/comments"
        target = f"scope={SCOPE}&item_id={self.observation.id}"

        listed = self.client.get(f"{base}?{target}").json()["results"]
        unscoped = self.client.get(base).json()["results"]
        detail = self.client.get(f"{base}/{self.note.id}")
        thread = self.client.get(f"{base}/{self.note.id}/thread")
        count = self.client.get(f"{base}/count?{target}").json()["count"]
        created = self.client.post(base, {"content": "my note", "scope": SCOPE, "item_id": str(self.observation.id)})
        reply = self.client.post(base, {"content": "my reply", "scope": SCOPE, "source_comment": str(self.note.id)})

        assert [c["id"] for c in listed] == ([str(self.note.id)] if allowed else [])
        # Product-owned scopes never ride along on an unscoped list, whatever the caller's access.
        assert unscoped == []
        assert detail.status_code == (status.HTTP_200_OK if allowed else status.HTTP_404_NOT_FOUND)
        assert thread.status_code == (status.HTTP_200_OK if allowed else status.HTTP_404_NOT_FOUND)
        assert count == (1 if allowed else 0)
        assert created.status_code == (status.HTTP_201_CREATED if allowed else status.HTTP_403_FORBIDDEN)
        assert reply.status_code == (status.HTTP_201_CREATED if allowed else status.HTTP_403_FORBIDDEN)

    @parameterized.expand([("denied", "none", False), ("viewer", "viewer", True)])
    @mock.patch("posthog.api.comments.send_mention_notifications")
    @mock.patch("posthog.api.comments.produce_discussion_mention_events")
    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    def test_mentions_reach_only_members_who_can_view_the_observation(
        self,
        _name: str,
        access_level: str,
        notified: bool,
        send_email: mock.Mock,
        produce_events: mock.Mock,
        send_notifications: mock.Mock,
    ) -> None:
        self._set_member_scanner_access(access_level)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "PM, please look",
                "scope": SCOPE,
                "item_id": str(self.observation.id),
                "mentions": [self.member.id],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        if notified:
            assert send_email.call_args.args[1] == [self.member.id]
        else:
            send_email.assert_not_called()
            send_notifications.assert_not_called()

    def test_note_content_is_masked_in_activity_log(self) -> None:
        Comment.objects.create(
            team=self.team,
            scope=SCOPE,
            item_id=str(self.observation.id),
            content="secret reply",
            created_by=self.user,
            source_comment=self.note,
        )

        entries = ActivityLog.objects.filter(team_id=self.team.id, activity="commented", scope__in=[SCOPE, "Comment"])

        assert sorted(entry.scope for entry in entries) == ["Comment", SCOPE]
        for entry in entries:
            assert entry.detail is not None
            assert entry.detail["changes"][0]["after"] == "masked"

    @mock.patch("posthog.tasks.email.send_discussions_mentioned.delay")
    @mock.patch("posthog.models.comment.utils.produce_internal_event")
    @mock.patch("products.notifications.backend.facade.api.create_notification")
    def test_mention_fanout_carries_no_note_text(
        self, create_notification: mock.Mock, produce_event: mock.Mock, send_email: mock.Mock
    ) -> None:
        # Notifications and CDP mention events are read later without an observation access check.
        self._set_member_scanner_access("viewer")

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {
                "content": "checkout secret",
                "scope": SCOPE,
                "item_id": str(self.observation.id),
                "mentions": [self.member.id],
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        notification = create_notification.call_args.args[0]
        event = produce_event.call_args.kwargs["event"]
        assert notification.body == OBSERVATION_NOTE_PLACEHOLDER[:200]
        assert event.properties["comment_content"] == OBSERVATION_NOTE_PLACEHOLDER
        assert "checkout secret" not in f"{notification} {event.properties}"

    def _observation(self, scanner: ReplayScanner, session_id: str, **fields: object) -> ReplayObservation:
        values: dict[str, object] = {
            "status": ObservationStatus.SUCCEEDED,
            "completed_at": timezone.now(),
            **fields,
        }
        return ReplayObservation.objects.create(
            scanner=scanner,
            team=self.team,
            session_id=session_id,
            scanner_snapshot=snapshot_for(scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            **values,
        )

    @parameterized.expand(
        [
            ("note_to_other_observation", "note", {"item_id": "other"}, "item_id"),
            ("other_comment_into_observation", "notebook_comment", {"scope": SCOPE, "item_id": "target"}, "item_id"),
            ("reply_to_other_thread", "reply", {"source_comment": "other_root"}, "source_comment"),
        ]
    )
    def test_comment_cannot_move_across_an_observation_boundary(
        self, _name: str, moved: str, change: dict[str, str], error_attr: str
    ) -> None:
        # /thread authorizes only the root, so a moved comment would carry note text across the access check.
        other = self._observation(self.scanner, "s-other")
        other_root = Comment.objects.create(
            team=self.team, scope=SCOPE, item_id=str(other.id), content="other thread", created_by=self.user
        )
        comment = {
            "note": self.note,
            "notebook_comment": Comment.objects.create(
                team=self.team, scope="Notebook", item_id="n1", content="root", created_by=self.user
            ),
            "reply": Comment.objects.create(
                team=self.team,
                scope=SCOPE,
                item_id=str(self.observation.id),
                content="reply",
                created_by=self.user,
                source_comment=self.note,
            ),
        }[moved]
        before = (comment.scope, comment.item_id, comment.source_comment_id)
        values = {"other": str(other.id), "target": str(self.observation.id), "other_root": str(other_root.id)}

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{comment.id}",
            {"content": "moved", **{key: values.get(value, value) for key, value in change.items()}},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == error_attr
        comment.refresh_from_db()
        assert (comment.scope, comment.item_id, comment.source_comment_id) == before

    @parameterized.expand(
        [
            ("failed", {"status": ObservationStatus.FAILED, "error_reason": "provider_transient:Timed out."}),
            ("running", {"status": ObservationStatus.RUNNING, "completed_at": None}),
        ]
    )
    def test_notes_need_a_finished_scan(self, _name: str, fields: dict[str, object]) -> None:
        # A retry deletes an unfinished row and gives the new scan a new id, which would strand its notes.
        unfinished = self._observation(self.scanner, "s-unfinished", **fields)

        response = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "too early", "scope": SCOPE, "item_id": str(unfinished.id)},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "item_id"
        assert not Comment.objects.filter(item_id=str(unfinished.id)).exists()

    @mock.patch("posthog.api.comments.CommentViewSet._slack_mirror_flag_enabled", return_value=True)
    def test_note_cannot_be_sent_to_slack(self, _flag: mock.Mock) -> None:
        # A Slack channel has no observation access check, in either direction.
        response = self.client.post(
            f"/api/projects/{self.team.id}/comments/{self.note.id}/send_to_slack/",
            {"integration_id": 1, "channel_id": "C1"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["detail"] == "Replay Vision observation notes cannot be sent to Slack"
        assert not CommentSlackThread.objects.for_team(self.team.id).filter(source_comment_id=self.note.id).exists()

    def test_scanner_delete_removes_the_notes_on_its_observations(self) -> None:
        reply = Comment.objects.create(
            team=self.team,
            scope=SCOPE,
            item_id=str(self.observation.id),
            content="reply",
            created_by=self.user,
            source_comment=self.note,
        )
        other_scanner = ReplayScanner.objects.create(
            team=self.team,
            name="Signup monitor",
            scanner_type=ScannerType.MONITOR,
            scanner_config={"prompt": "did the user sign up?"},
            model=ScannerModel.GEMINI_3_8_FLASH,
        )
        kept = Comment.objects.create(
            team=self.team,
            scope=SCOPE,
            item_id=str(self._observation(other_scanner, "s-kept").id),
            content="kept",
            created_by=self.user,
        )

        # Any spelling of the UUID resolves the observation, so the write stores one spelling for the cleanup to match.
        uppercase = self.client.post(
            f"/api/projects/{self.team.id}/comments",
            {"content": "uppercase id", "scope": SCOPE, "item_id": str(self.observation.id).upper()},
        )

        self.scanner.delete()

        assert uppercase.status_code == status.HTTP_201_CREATED
        assert not Comment.objects.filter(id__in=[self.note.id, reply.id, uppercase.json()["id"]]).exists()
        assert Comment.objects.filter(id=kept.id).exists()

    @mock.patch("posthog.tasks.email.is_email_available", return_value=True)
    @mock.patch("posthog.tasks.email.EmailMessage")
    def test_mention_email_sent_after_access_is_revoked_carries_no_note_text(
        self, email_message: mock.Mock, _email_available: mock.Mock
    ) -> None:
        self._set_member_scanner_access("viewer")
        note = Comment.objects.create(
            team=self.team,
            scope=SCOPE,
            item_id=str(self.observation.id),
            content="checkout secret",
            created_by=self.user,
        )
        # The email task runs after the mention was authorized, so access can be gone by then.
        AccessControl.objects.filter(resource="replay_scanner", resource_id=str(self.scanner.id)).update(
            access_level="none"
        )

        send_discussions_mentioned(str(note.id), [self.member.id], "")

        context = email_message.call_args.kwargs["template_context"]
        assert context["content"] == OBSERVATION_NOTE_PLACEHOLDER
        assert "checkout secret" not in str(email_message.call_args)
