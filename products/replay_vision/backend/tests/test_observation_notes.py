from posthog.test.base import APIBaseTest
from unittest import mock

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.comment import Comment

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
