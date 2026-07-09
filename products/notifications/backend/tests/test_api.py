import uuid
from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from rest_framework.test import APIClient

from posthog.models import Organization, Team, User

from products.notifications.backend.cache import _unread_count_cache_key
from products.notifications.backend.models import NotificationEvent, NotificationReadState


class TestNotificationsAPI(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "apitest@test.com", "password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.feature_flag_patcher = patch(
            "products.notifications.backend.presentation.views.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.feature_flag_patcher.start()

        self.event = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="comment_mention",
            title="Test notification",
            body="Test body",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def test_list_notifications(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/")
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 1
        assert resp.json()["results"][0]["title"] == "Test notification"
        assert resp.json()["results"][0]["read"] is False

    def test_unread_count(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_mark_read(self):
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/mark_read/")
        assert resp.status_code == 200
        assert NotificationReadState.objects.filter(notification_event=self.event, user=self.user).exists()

    def test_mark_unread(self):
        NotificationReadState.objects.create(notification_event=self.event, user=self.user)
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/mark_unread/")
        assert resp.status_code == 200
        assert not NotificationReadState.objects.filter(notification_event=self.event, user=self.user).exists()

    def test_mark_read_org_level_notification(self):
        org_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=None,
            notification_type="comment_mention",
            title="Org-level notification",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{org_event.id}/mark_read/")
        assert resp.status_code == 200
        assert NotificationReadState.objects.filter(notification_event=org_event, user=self.user).exists()

    def test_mark_unread_org_level_notification(self):
        org_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=None,
            notification_type="comment_mention",
            title="Org-level notification",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        NotificationReadState.objects.create(notification_event=org_event, user=self.user)
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{org_event.id}/mark_unread/")
        assert resp.status_code == 200
        assert not NotificationReadState.objects.filter(notification_event=org_event, user=self.user).exists()

    def test_mark_read_non_recipient_returns_404(self):
        other_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=None,
            notification_type="comment_mention",
            title="Not for me",
            body="",
            target_type="user",
            target_id="999999",
            resolved_user_ids=[999999],
        )
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{other_event.id}/mark_read/")
        assert resp.status_code == 404
        assert not NotificationReadState.objects.filter(notification_event=other_event, user=self.user).exists()

    def test_mark_all_read(self):
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Second",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/mark_all_read/")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        assert NotificationReadState.objects.count() == 2

    def test_unread_count_is_cached_after_first_call(self):
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        assert cache.get(cache_key) is None

        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        assert cache.get(cache_key) == 1

    def test_unread_count_serves_from_cache(self):
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, 42, 60)

        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 42

    def test_mark_read_invalidates_cache(self):
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, 5, 60)

        self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/mark_read/")
        assert cache.get(cache_key) is None

    def test_mark_unread_invalidates_cache(self):
        NotificationReadState.objects.create(notification_event=self.event, user=self.user)
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, 0, 60)

        self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/mark_unread/")
        assert cache.get(cache_key) is None

    def test_mark_all_read_sets_cache_to_zero(self):
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, 5, 60)

        self.client.post(f"/api/environments/{self.team.id}/notifications/mark_all_read/")
        assert cache.get(cache_key) == 0

    def test_other_users_notifications_not_visible(self):
        other_user = User.objects.create_and_join(self.organization, "other@test.com", "password")
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="comment_mention",
            title="Not for me",
            body="",
            target_type="user",
            target_id=str(other_user.id),
            resolved_user_ids=[other_user.id],
        )
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/")
        assert len(resp.json()["results"]) == 1

    def test_list_filter_by_notification_type(self):
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Alert",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/?notification_type=alert_firing")
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["notification_type"] == "alert_firing"

    def test_list_filter_by_target(self):
        other_user = User.objects.create_and_join(self.organization, "other2@test.com", "password")
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Other",
            body="",
            target_type="user",
            target_id=str(other_user.id),
            resolved_user_ids=[self.user.id],
        )
        resp = self.client.get(
            f"/api/environments/{self.team.id}/notifications/?target_type=user&target_id={self.user.id}"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["target_id"] == str(self.user.id)

    def test_list_filter_by_resource(self):
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="With resource",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
            resource_type="insight",
            resource_id="abc123",
        )
        resp = self.client.get(
            f"/api/environments/{self.team.id}/notifications/?resource_type=insight&resource_id=abc123"
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert len(results) == 1
        assert results[0]["resource_id"] == "abc123"

    def test_list_filter_invalid_datetime_returns_400(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/?created_after=not-a-date")
        assert resp.status_code == 400

    def test_list_filter_combines_with_and(self):
        # event with type=alert_firing but different resource — should not match
        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Other resource",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
            resource_type="insight",
            resource_id="other",
        )
        # event matching both filters
        match = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Match",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
            resource_type="insight",
            resource_id="abc",
        )
        resp = self.client.get(
            f"/api/environments/{self.team.id}/notifications/"
            f"?notification_type=alert_firing&resource_type=insight&resource_id=abc"
        )
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()["results"]]
        assert ids == [str(match.id)]

    def test_list_filter_by_created_window(self):
        old = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Old",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        NotificationEvent.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))

        cutoff = (timezone.now() - timedelta(days=1)).isoformat()
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/?created_after={cutoff}")
        assert resp.status_code == 200
        ids = {r["id"] for r in resp.json()["results"]}
        assert str(old.id) not in ids
        assert str(self.event.id) in ids

    def test_mark_read_bulk(self):
        e2 = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Two",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        e3 = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Three",
            body="",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_read_bulk/",
            {"notification_ids": [str(self.event.id), str(e2.id), str(e3.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3
        for ev in (self.event, e2, e3):
            assert NotificationReadState.objects.filter(notification_event=ev, user=self.user).exists()

    def test_mark_read_bulk_skips_non_recipient(self):
        other_user_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Other",
            body="",
            target_type="user",
            target_id="999",
            resolved_user_ids=[],
        )
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_read_bulk/",
            {"notification_ids": [str(other_user_event.id), str(self.event.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1
        assert not NotificationReadState.objects.filter(notification_event=other_user_event, user=self.user).exists()

    def test_mark_unread_bulk(self):
        NotificationReadState.objects.create(notification_event=self.event, user=self.user)
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_unread_bulk/",
            {"notification_ids": [str(self.event.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1
        assert not NotificationReadState.objects.filter(notification_event=self.event, user=self.user).exists()

    def test_mark_read_bulk_empty(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_read_bulk/",
            {"notification_ids": []},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0

    def test_mark_unread_bulk_skips_non_recipient(self):
        other_user_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Other",
            body="",
            target_type="user",
            target_id="999",
            resolved_user_ids=[],
        )
        # Pre-create a read state for the user's own event so it has something to delete
        NotificationReadState.objects.create(notification_event=self.event, user=self.user)
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_unread_bulk/",
            {"notification_ids": [str(other_user_event.id), str(self.event.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1
        assert not NotificationReadState.objects.filter(notification_event=self.event, user=self.user).exists()

    def test_mark_read_bulk_non_list_returns_400(self):
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_read_bulk/",
            {"notification_ids": "not-a-list"},
            format="json",
        )
        assert resp.status_code == 400

    def test_mark_read_bulk_too_many_ids_returns_400(self):
        ids = [str(uuid.uuid4()) for _ in range(501)]
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_read_bulk/",
            {"notification_ids": ids},
            format="json",
        )
        assert resp.status_code == 400

    def test_mark_unread_bulk_too_many_ids_returns_400(self):
        ids = [str(uuid.uuid4()) for _ in range(501)]
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/mark_unread_bulk/",
            {"notification_ids": ids},
            format="json",
        )
        assert resp.status_code == 400


class TestNotificationsAPIFeatureFlagDisabled(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_and_join(self.organization, "apitest@test.com", "password")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.feature_flag_patcher = patch(
            "products.notifications.backend.presentation.views.posthoganalytics.feature_enabled",
            return_value=False,
        )
        self.feature_flag_patcher.start()

        NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="comment_mention",
            title="Test notification",
            body="Test body",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )

    def tearDown(self):
        self.feature_flag_patcher.stop()
        super().tearDown()

    def test_list_returns_empty_when_ff_disabled(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/")
        assert resp.status_code == 200
        assert resp.json()["results"] == []

    def test_unread_count_returns_zero_when_ff_disabled(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
