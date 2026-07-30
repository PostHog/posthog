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
from products.notifications.backend.logic import create_notification, publish_resource_edited
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

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic._publish_to_kafka")
    def test_create_notification_for_team(self, mock_publish, mock_ff):
        user2 = User.objects.create_and_join(self.organization, "team_test@test.com", "password")

        data = NotificationData(
            team_id=self.team.id,
            notification_type=NotificationType.COMMENT_MENTION,
            title="Team alert",
            body="Something happened",
            target_type=TargetType.TEAM,
            target_id=str(self.team.id),
        )
        event = create_notification(data)

        assert event is not None
        assert set(event.resolved_user_ids) == {self.user.id, user2.id}

    def test_resolve_team_excludes_org_members_without_project_access(self):
        from posthog.models import OrganizationMembership

        from ee.models.rbac.access_control import AccessControl

        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()

        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=None,
            role=None,
            access_level="none",
        )

        allowed_user = User.objects.create_and_join(self.organization, "allowed@test.com", "password")
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=allowed_user),
            access_level="member",
        )
        denied_user = User.objects.create_and_join(self.organization, "denied@test.com", "password")

        result = RecipientsResolver().resolve(TargetType.TEAM, str(self.team.id), self.team.id)

        assert allowed_user.id in result
        assert denied_user.id not in result

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

    def test_passthrough_when_org_lacks_access_control(self):
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
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
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


class TestPublishResourceEdited(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="RE Org")
        self.team = Team.objects.create(organization=self.organization, name="RE Team")
        self.user = User.objects.create_and_join(self.organization, "re@test.com", "password")

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic.get_producer")
    def test_publishes_transient_event_without_persisting(self, mock_get_producer, mock_ff):
        producer = mock_get_producer.return_value

        with self.captureOnCommitCallbacks(execute=True):
            publish_resource_edited(
                team=self.team,
                resource_type="HogFlow",
                resource_id="flow-123",
                updated_at="2026-06-16T00:00:00+00:00",
                actor_user_id=self.user.id,
                ac_resource_type="hog_flow",
            )

        producer.produce.assert_called_once()
        payload = producer.produce.call_args.kwargs["data"]
        assert payload["notification_type"] == "resource_edited"
        assert payload["resource_type"] == "HogFlow"
        assert payload["resource_id"] == "flow-123"
        assert payload["updated_at"] == "2026-06-16T00:00:00+00:00"
        assert self.user.id in payload["resolved_user_ids"]
        # Editor-state sync only — it must never become an inbox notification.
        assert NotificationEvent.objects.count() == 0

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=False)
    @patch("products.notifications.backend.logic.get_producer")
    def test_noops_when_flag_disabled(self, mock_get_producer, mock_ff):
        with self.captureOnCommitCallbacks(execute=True):
            publish_resource_edited(
                team=self.team,
                resource_type="HogFlow",
                resource_id="flow-123",
                updated_at="2026-06-16T00:00:00+00:00",
            )

        mock_get_producer.assert_not_called()

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic.get_producer")
    @patch.object(RecipientsResolver, "resolve", return_value=[])
    def test_noops_when_no_recipients(self, mock_resolve, mock_get_producer, mock_ff):
        with self.captureOnCommitCallbacks(execute=True):
            publish_resource_edited(
                team=self.team,
                resource_type="HogFlow",
                resource_id="flow-123",
                updated_at="2026-06-16T00:00:00+00:00",
            )

        mock_get_producer.assert_not_called()

    @patch("products.notifications.backend.logic.posthoganalytics.feature_enabled", return_value=True)
    @patch("products.notifications.backend.logic.get_producer")
    @patch.object(RecipientsResolver, "filter_by_access_control")
    def test_skips_access_control_filtering_for_non_ac_resource(self, mock_ac_filter, mock_get_producer, mock_ff):
        # annotation is not an access-controlled resource type, so recipients are not AC-filtered.
        with self.captureOnCommitCallbacks(execute=True):
            publish_resource_edited(
                team=self.team,
                resource_type="Annotation",
                resource_id="annotation-123",
                updated_at="2026-06-16T00:00:00+00:00",
                ac_resource_type="annotation",
            )

        mock_ac_filter.assert_not_called()
        mock_get_producer.return_value.produce.assert_called_once()
