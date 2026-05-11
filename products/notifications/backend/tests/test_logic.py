import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User

from products.notifications.backend.cache import _unread_count_cache_key
from products.notifications.backend.facade.contracts import NotificationData
from products.notifications.backend.facade.enums import (
    NotificationOnlyResourceType,
    NotificationType,
    Priority,
    SourceType,
    TargetType,
)
from products.notifications.backend.logic import create_notification, publish_silent_push
from products.notifications.backend.models import NotificationEvent
from products.notifications.backend.resolvers import RecipientsResolver


class TestCreateNotification(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "test@test.com", "password")

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
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
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_for_organization(self, mock_publish, mock_ff):
        user2 = User.objects.create_and_join(self.organization, "test2@test.com", "password")

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Org-wide alert",
            body="Something happened",
            target_type=TargetType.ORGANIZATION,
            target_id=str(self.organization.id),
            priority=Priority.CRITICAL,
        )
        event = create_notification(data)

        assert event is not None
        assert set(event.resolved_user_ids) == {self.user.id, user2.id}

    def test_resolve_unknown_target_type_raises(self):
        resolver = RecipientsResolver()
        with pytest.raises(ValueError, match="Unknown target type"):
            resolver.resolve("nonexistent_type", "123", self.team.id)  # type: ignore[arg-type]

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_invalidates_cache_for_resolved_users(self, mock_publish, mock_ff):
        user2 = User.objects.create_and_join(self.organization, "cache_test@test.com", "password")
        key1 = _unread_count_cache_key(self.user.id, self.organization.id)
        key2 = _unread_count_cache_key(user2.id, self.organization.id)
        cache.set(key1, 3, 60)
        cache.set(key2, 7, 60)

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Cache invalidation test",
            body="",
            target_type=TargetType.ORGANIZATION,
            target_id=str(self.organization.id),
        )
        with self.captureOnCommitCallbacks(execute=True):
            create_notification(data)

        assert cache.get(key1) is None
        assert cache.get(key2) is None

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_with_source_type_and_id(self, mock_publish, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test notification",
            body="Test body",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
            source_type=SourceType.DASHBOARD,
            source_id="abc123",
        )
        with self.captureOnCommitCallbacks(execute=True):
            event = create_notification(data)

        assert event is not None
        assert event.source_type == "dashboard"
        assert event.source_id == "abc123"

        mock_publish.assert_called_once()
        kafka_data = mock_publish.call_args[0][0]
        assert kafka_data.source_type == "dashboard"
        assert kafka_data.source_id == "abc123"

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_without_source_type(self, mock_publish, mock_ff):
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
        assert event.source_type is None
        assert event.source_id is None

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

    @parameterized.expand(
        [
            (
                "muted_same_team",
                lambda team: {"realtime_notifications_disabled": {"comment_mention": {str(team.id): True}}},
                False,
            ),
            (
                "muted_other_type",
                lambda team: {"realtime_notifications_disabled": {"alert_firing": {str(team.id): True}}},
                True,
            ),
            (
                "muted_other_team",
                lambda team: {"realtime_notifications_disabled": {"comment_mention": {"99999": True}}},
                True,
            ),
            ("settings_none", lambda team: None, True),
            ("realtime_key_none", lambda team: {"realtime_notifications_disabled": None}, True),
        ]
    )
    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_respects_per_user_pref(
        self, _name, settings_factory, expect_notified, mock_publish, mock_ff
    ):
        settings = settings_factory(self.team)
        if settings is None:
            self.user.partial_notification_settings = None
        else:
            self.user.partial_notification_settings = settings
        self.user.save()

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="",
            target_type=TargetType.USER,
            target_id=str(self.user.id),
        )
        event = create_notification(data)

        if expect_notified:
            assert event is not None
            assert event.resolved_user_ids == [self.user.id]
        else:
            assert event is None

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_filters_org_target_by_per_user_pref(self, mock_publish, mock_ff):
        user2 = User.objects.create_and_join(self.organization, "muted@test.com", "password")
        user2.partial_notification_settings = {
            "realtime_notifications_disabled": {
                "comment_mention": {str(self.team.id): True},
            }
        }
        user2.save()

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Test",
            body="",
            target_type=TargetType.ORGANIZATION,
            target_id=str(self.organization.id),
        )
        event = create_notification(data)

        assert event is not None
        assert set(event.resolved_user_ids) == {self.user.id}


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
    @patch("products.notifications.backend.logic._publish_to_kafka")
    @patch.object(RecipientsResolver, "filter_by_access_control")
    def test_no_ac_filtering_for_notification_only_resource_types(self, mock_ac_filter, mock_publish, mock_ff):
        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
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


class TestPublishSilentPush(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Silent Push Org")
        self.team = Team.objects.create(organization=self.organization, name="Silent Push Team")
        self.user = User.objects.create_and_join(self.organization, "silent@test.com", "password")

    @patch("products.notifications.backend.logic.get_producer")
    def test_publishes_to_kafka(self, mock_get_producer):
        mock_producer = mock_get_producer.return_value
        publish_silent_push(
            organization_id=str(self.organization.id),
            team_id=self.team.id,
            event_type="conversations_unread_changed",
            user_ids=[self.user.id],
        )

        mock_producer.produce.assert_called_once()
        call_kwargs = mock_producer.produce.call_args[1]
        data = call_kwargs["data"]
        assert data["organization_id"] == str(self.organization.id)
        assert data["team_id"] == self.team.id
        assert data["notification_type"] == "conversations_unread_changed"
        assert data["resolved_user_ids"] == [self.user.id]
        assert data["silent"] is True
        assert call_kwargs["key"] == str(self.organization.id)

    @patch("products.notifications.backend.logic.get_producer")
    def test_skips_when_no_user_ids(self, mock_get_producer):
        publish_silent_push(
            organization_id=str(self.organization.id),
            team_id=self.team.id,
            event_type="conversations_unread_changed",
            user_ids=[],
        )
        mock_get_producer.assert_not_called()

    @patch("products.notifications.backend.logic.get_producer")
    def test_does_not_create_db_row(self, mock_get_producer):
        publish_silent_push(
            organization_id=str(self.organization.id),
            team_id=self.team.id,
            event_type="conversations_unread_changed",
            user_ids=[self.user.id],
        )
        assert NotificationEvent.objects.count() == 0
