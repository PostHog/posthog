from posthog.test.base import APIBaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment
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
        AccessControl.objects.create(
            team=self.team,
            resource="replay_scanner",
            resource_id=str(self.scanner.id),
            organization_member=self.member.organization_memberships.get(organization=self.organization),
            access_level=access_level,
        )

    @parameterized.expand([("denied", "none", False), ("viewer", "viewer", True)])
    def test_notes_follow_scanner_access(self, _name: str, access_level: str, allowed: bool) -> None:
        self._set_member_scanner_access(access_level)
        self.client.force_login(self.member)
        base = f"/api/projects/{self.team.id}/comments"

        listed = self.client.get(f"{base}?scope={SCOPE}&item_id={self.observation.id}").json()["results"]
        unscoped = self.client.get(base).json()["results"]
        detail = self.client.get(f"{base}/{self.note.id}")
        created = self.client.post(base, {"content": "my note", "scope": SCOPE, "item_id": str(self.observation.id)})

        assert [c["id"] for c in listed] == ([str(self.note.id)] if allowed else [])
        # Product-owned scopes never ride along on an unscoped list, whatever the caller's access.
        assert unscoped == []
        assert detail.status_code == (status.HTTP_200_OK if allowed else status.HTTP_404_NOT_FOUND)
        assert created.status_code == (status.HTTP_201_CREATED if allowed else status.HTTP_403_FORBIDDEN)

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

    @parameterized.expand(
        [
            ("note_to_other_observation", SCOPE, {"item_id": "other"}),
            ("other_comment_into_observation", "Notebook", {"scope": SCOPE, "item_id": "target"}),
        ]
    )
    def test_comment_cannot_move_across_an_observation_boundary(
        self, _name: str, root_scope: str, change: dict[str, str]
    ) -> None:
        # /thread authorizes only the root, so a moved root would carry its replies across the access check.
        other = ReplayObservation.objects.create(
            scanner=self.scanner,
            team=self.team,
            session_id="s-other",
            status=ObservationStatus.SUCCEEDED,
            scanner_snapshot=snapshot_for(self.scanner),
            triggered_by=ObservationTrigger.SCHEDULE,
            completed_at=timezone.now(),
        )
        item_ids = {"other": str(other.id), "target": str(self.observation.id)}
        root = Comment.objects.create(
            team=self.team,
            scope=root_scope,
            item_id=str(self.observation.id) if root_scope == SCOPE else "n1",
            content="root",
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/comments/{root.id}",
            {"content": "root", **{key: item_ids.get(value, value) for key, value in change.items()}},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "item_id"
        root.refresh_from_db()
        assert (root.scope, root.item_id) == (root_scope, str(self.observation.id) if root_scope == SCOPE else "n1")

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
