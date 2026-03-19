import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User

from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import (
    NotificationOnlyResourceType,
    NotificationType,
    Priority,
    TargetType,
)
from products.notifications.backend.logic import create_notification
from products.notifications.backend.models import NotificationEvent
from products.notifications.backend.resolvers import RecipientsResolver


class TestCreateNotification(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@test.com", "password")

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    def test_create_notification_for_user(self, mock_publish, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test notification",
            body="Test body",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
        )
        event = create_notification(data)

        assert event is not None
        assert event.resolved_user_ids == [self.user.id]
        assert event.organization_id == self.organization.id
        assert event.notification_type == "comment_mention"
        assert NotificationEvent.objects.count() == 1

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    def test_create_notification_for_organization(self, mock_publish, mock_ff):
        user2 = User.objects.create_and_join(self.organization, "test2@test.com", "password")

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.ALERT_FIRING,
            title="Org-wide alert",
            body="Something happened",
            target_type=TargetType.ORGANIZATION,
            target_id=str(self.organization.id),
            priority=Priority.URGENT,
        )
        event = create_notification(data)

        assert event is not None
        assert set(event.resolved_user_ids) == {self.user.id, user2.id}

    def test_resolve_unknown_target_type_raises(self):
        resolver = RecipientsResolver()
        with pytest.raises(ValueError, match="Unknown target type"):
            resolver.resolve("nonexistent_type", "123", self.team.id)

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=False)
    def test_feature_flag_disabled_returns_none(self, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
        )
        event = create_notification(data)
        assert event is None
        assert NotificationEvent.objects.count() == 0


class TestAccessControlFiltering(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="AC Test Org")
        self.team = Team.objects.create(organization=self.organization, name="AC Test Team")
        self.user = User.objects.create_and_join(self.organization, "ac1@test.com", "password")
        self.user2 = User.objects.create_and_join(self.organization, "ac2@test.com", "password")
        self.resolver = RecipientsResolver()

    def test_passthrough_when_org_lacks_advanced_permissions(self):
        self.organization.available_product_features = []
        self.organization.save()

        user_ids = [self.user.id, self.user2.id]
        result = self.resolver.filter_by_access_control(user_ids, "dashboard", self.team)
        assert set(result) == {self.user.id, self.user2.id}

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_redis")
    @patch.object(RecipientsResolver, "filter_by_access_control")
    def test_no_ac_filtering_for_notification_only_resource_types(self, mock_ac_filter, mock_publish, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.PIPELINE_FAILURE,
            title="Pipeline failed",
            body="",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
            resource_type=NotificationOnlyResourceType.PIPELINE,
        )
        create_notification(data)
        mock_ac_filter.assert_not_called()

    @patch("products.notifications.backend.resolvers.UserAccessControl")
    def test_excludes_users_without_access(self, mock_uac_cls):
        self.organization.available_product_features = [{"key": AvailableFeature.ADVANCED_PERMISSIONS}]
        self.organization.save()

        allowed_user_id = self.user.id

        class FakeUAC:
            def __init__(self, user, team):
                self._user_id = user.id

            @property
            def access_controls_supported(self):
                return True

            def check_access_level_for_resource(self, resource, level):
                return self._user_id == allowed_user_id

        mock_uac_cls.side_effect = FakeUAC

        user_ids = [self.user.id, self.user2.id]
        result = self.resolver.filter_by_access_control(user_ids, "dashboard", self.team)
        assert result == [self.user.id]
