import uuid
from datetime import timedelta
from types import EllipsisType

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, Team, User

from products.access_control.backend.models.access_control import AccessControl
from products.notifications.backend.cache import _unread_count_cache_key
from products.notifications.backend.models import NotificationArchiveState, NotificationEvent, NotificationReadState


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

    def test_access_is_checked_in_each_notifications_own_project(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save(update_fields=["available_product_features"])
        locked_team = Team.objects.create(organization=self.organization, name="Locked catalog")
        self.event.resource_type = "data_catalog"
        self.event.save(update_fields=["resource_type"])
        self._create_notification("Locked", team=locked_team, resource_type="data_catalog")
        AccessControl.objects.create(
            team=locked_team,
            resource="data_catalog",
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=self.user),
            access_level="none",
        )

        for url_team in (self.team, locked_team):
            ids = {
                row["id"]
                for row in self.client.get(f"/api/environments/{url_team.id}/notifications/").json()["results"]
            }
            assert ids == {str(self.event.id)}, url_team.name

    def test_catalog_notification_disappears_after_access_revocation(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save(update_fields=["available_product_features"])
        self.event.resource_type = "data_catalog"
        self.event.save(update_fields=["resource_type"])
        url = f"/api/environments/{self.team.id}/notifications/"
        assert [event["id"] for event in self.client.get(url).json()["results"]] == [str(self.event.id)]
        AccessControl.objects.create(
            team=self.team,
            resource="data_catalog",
            organization_member=OrganizationMembership.objects.get(organization=self.organization, user=self.user),
            access_level="none",
        )
        cache.clear()
        assert self.client.get(url).json()["results"] == []
        assert self.client.get(url + "unread_count/").json()["count"] == 0

    def test_notification_from_a_project_the_user_cannot_open_is_hidden(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save(update_fields=["available_product_features"])
        private_team = Team.objects.create(organization=self.organization, name="Private")
        private_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=private_team,
            notification_type="workflow_suggestion",
            title="Secret workflow",
            target_type="user",
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
        )
        url = f"/api/environments/{self.team.id}/notifications/"
        assert {e["id"] for e in self.client.get(url).json()["results"]} == {str(self.event.id), str(private_event.id)}
        AccessControl.objects.create(
            team=private_team, resource="project", resource_id=str(private_team.id), access_level="none"
        )
        cache.clear()
        assert [e["id"] for e in self.client.get(url).json()["results"]] == [str(self.event.id)]
        assert self.client.get(url + "unread_count/").json()["count"] == 1

    def test_unread_count(self):
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json() == {"count": 1, "direct_count": 1, "has_critical": False}

    def test_unread_count_separates_direct_and_critical(self):
        self._create_notification("Team failure", target_type="team", priority="critical")
        read_critical = self._create_notification("Read critical", priority="critical")
        NotificationReadState.objects.create(notification_event=read_critical, user=self.user)

        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")

        assert resp.json() == {"count": 2, "direct_count": 1, "has_critical": True}

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

    @parameterized.expand(
        [
            ("mark_read", "post", "mark_read/"),
            ("retrieve", "get", ""),
            ("unarchive", "post", "unarchive/"),
        ]
    )
    def test_detail_endpoints_return_404_for_non_recipient(self, _name: str, method: str, suffix: str) -> None:
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
        url = f"/api/environments/{self.team.id}/notifications/{other_event.id}/{suffix}"
        resp = getattr(self.client, method)(url)
        assert resp.status_code == 404
        assert not NotificationReadState.objects.filter(notification_event=other_event, user=self.user).exists()

    def test_retrieve_returns_archived_state(self) -> None:
        self.client.post(f"/api/environments/{self.team.id}/notifications/{self.event.id}/archive/")
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/{self.event.id}/")
        assert resp.status_code == 200
        assert resp.json()["archived"] is True

    def test_mark_all_read_only_marks_what_matches_the_filters(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_project_event = self._create_notification("Elsewhere", team=other_team)
        org_event = self._create_notification("Org-wide", team=None)

        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/mark_all_read/?team_id={self.team.id}")

        assert resp.json()["updated"] == 2
        read_ids = set(NotificationReadState.objects.values_list("notification_event_id", flat=True))
        assert read_ids == {self.event.id, org_event.id}
        assert other_project_event.id not in read_ids

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
        assert cache.get(cache_key) == {"count": 1, "direct_count": 1, "has_critical": False}

    def test_unread_count_serves_from_cache(self):
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, {"count": 42, "direct_count": 40, "has_critical": True}, 60)

        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.status_code == 200
        assert resp.json() == {"count": 42, "direct_count": 40, "has_critical": True}

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

    def test_mark_all_read_invalidates_cache(self):
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, {"count": 5, "direct_count": 5, "has_critical": False}, 60)

        self.client.post(f"/api/environments/{self.team.id}/notifications/mark_all_read/")
        assert cache.get(cache_key) is None

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

    @parameterized.expand(
        [
            ("unread_only", "read=false", {"unread_mention", "team_failure", "org_digest"}),
            ("read_only", "read=true", {"read_alert", "other_project"}),
            (
                "type_list",
                "notification_type=comment_mention,alert_firing",
                {"unread_mention", "read_alert", "other_project"},
            ),
            ("target_list", "target_type=team,organization", {"team_failure", "org_digest"}),
            ("priority", "priority=critical", {"team_failure"}),
            ("project_keeps_org_wide", "team_id={other_team}", {"other_project", "org_digest"}),
        ]
    )
    def test_list_filters(self, _name: str, query: str, expected: set[str]) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other")
        self.event.delete()
        events = {
            "unread_mention": self._create_notification(notification_type="comment_mention"),
            "read_alert": self._create_notification(notification_type="alert_firing"),
            "team_failure": self._create_notification(
                notification_type="pipeline_failure", target_type="team", priority="critical"
            ),
            "org_digest": self._create_notification(
                notification_type="web_analytics_digest", target_type="organization", team=None
            ),
            "other_project": self._create_notification(notification_type="comment_mention", team=other_team),
        }
        NotificationReadState.objects.create(notification_event=events["read_alert"], user=self.user)
        NotificationReadState.objects.create(notification_event=events["other_project"], user=self.user)

        resp = self.client.get(
            f"/api/environments/{self.team.id}/notifications/?{query.format(other_team=other_team.id)}"
        )

        assert resp.status_code == 200
        names_by_id = {str(event.id): name for name, event in events.items()}
        assert {names_by_id[row["id"]] for row in resp.json()["results"]} == expected

    @parameterized.expand(
        [
            ("unknown_type", "notification_type=comment_mention,not_a_type"),
            ("unknown_target", "target_type=everyone"),
            ("unknown_priority", "priority=urgent"),
            ("bad_cursor", "before=yesterday"),
            ("empty_type_list", "notification_type=,"),
        ]
    )
    def test_list_rejects_unknown_filter_values(self, _name: str, query: str) -> None:
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/?{query}")
        assert resp.status_code == 400

    def test_cursor_paging_skips_nothing_when_rows_are_archived_between_pages(self) -> None:
        for index in range(4):
            self._create_notification(f"Item {index}")
        url = f"/api/environments/{self.team.id}/notifications/?limit=2"

        first_page = self.client.get(url).json()
        for row in first_page["results"]:
            self.client.post(f"/api/environments/{self.team.id}/notifications/{row['id']}/archive/")
        seen = [row["id"] for row in first_page["results"]]
        cursor = first_page["next_cursor"]
        while cursor:
            page = self.client.get(url, {"before": cursor}).json()
            seen += [row["id"] for row in page["results"]]
            cursor = page["next_cursor"]

        assert len(seen) == 5
        assert len(set(seen)) == 5

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

    def _create_notification(
        self,
        title: str = "Extra",
        *,
        notification_type: str = "alert_firing",
        target_type: str = "user",
        priority: str = "normal",
        team: Team | None | EllipsisType = ...,
        resource_type: str | None = None,
        resource_id: str = "",
    ) -> NotificationEvent:
        return NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team if isinstance(team, EllipsisType) else team,
            notification_type=notification_type,
            priority=priority,
            title=title,
            body="",
            target_type=target_type,
            target_id=str(self.user.id),
            resolved_user_ids=[self.user.id],
            resource_type=resource_type,
            resource_id=resource_id,
        )

    def test_archive_notification(self):
        event = self._create_notification()
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{event.id}/archive/")
        assert resp.status_code == 200
        assert NotificationArchiveState.objects.filter(notification_event=event, user=self.user).exists()

    def test_archived_notification_excluded_from_list(self):
        event = self._create_notification()
        NotificationArchiveState.objects.create(notification_event=event, user=self.user)
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/")
        ids = {r["id"] for r in resp.json()["results"]}
        assert str(event.id) not in ids
        assert str(self.event.id) in ids

    def test_archived_list_returns_only_archived(self):
        archived = self._create_notification("Archived item")
        NotificationArchiveState.objects.create(notification_event=archived, user=self.user)
        active = self._create_notification("Still active")
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/?archived=true")
        ids = {r["id"] for r in resp.json()["results"]}
        assert str(archived.id) in ids
        assert str(active.id) not in ids
        assert str(self.event.id) not in ids

    def test_archived_notification_excluded_from_unread_count(self):
        event = self._create_notification()
        NotificationArchiveState.objects.create(notification_event=event, user=self.user)
        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/unread_count/")
        assert resp.json()["count"] == 1

    def test_archive_invalidates_cache(self):
        event = self._create_notification()
        cache_key = _unread_count_cache_key(self.user.id, self.organization.id)
        cache.set(cache_key, 5, 60)
        self.client.post(f"/api/environments/{self.team.id}/notifications/{event.id}/archive/")
        assert cache.get(cache_key) is None

    def test_archive_bulk(self):
        a1 = self._create_notification("Bulk 1")
        a2 = self._create_notification("Bulk 2")
        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/archive_bulk/",
            {"notification_ids": [str(a1.id), str(a2.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 2
        for ev in (a1, a2):
            assert NotificationArchiveState.objects.filter(notification_event=ev, user=self.user).exists()

    def test_archive_bulk_skips_non_recipient(self):
        other_event = NotificationEvent.objects.create(
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
            f"/api/environments/{self.team.id}/notifications/archive_bulk/",
            {"notification_ids": [str(other_event.id)]},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 0
        assert not NotificationArchiveState.objects.filter(notification_event=other_event, user=self.user).exists()

    def test_archive_detail_skips_non_recipient(self):
        other_event = NotificationEvent.objects.create(
            organization=self.organization,
            team=self.team,
            notification_type="alert_firing",
            title="Other",
            body="",
            target_type="user",
            target_id="999",
            resolved_user_ids=[],
        )
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/{other_event.id}/archive/")
        assert resp.status_code == 404
        assert not NotificationArchiveState.objects.filter(notification_event=other_event, user=self.user).exists()

    def test_archive_all(self):
        a1 = self._create_notification("A1")
        a2 = self._create_notification("A2")
        resp = self.client.post(f"/api/environments/{self.team.id}/notifications/archive_all/")
        assert resp.status_code == 200
        assert resp.json()["updated"] == 3
        for ev in (self.event, a1, a2):
            assert NotificationArchiveState.objects.filter(notification_event=ev, user=self.user).exists()

    def test_archive_all_with_group_filters_archives_every_item_and_returns_ids_to_undo(self) -> None:
        group = [
            self._create_notification(f"Run {index}", resource_type="batch_export", resource_id="be-1")
            for index in range(25)
        ]
        other = self._create_notification("Other export", resource_type="batch_export", resource_id="be-2")
        NotificationReadState.objects.create(notification_event=group[0], user=self.user)
        base = f"/api/environments/{self.team.id}/notifications"

        resp = self.client.post(
            f"{base}/archive_all/?notification_type=alert_firing&resource_type=batch_export&resource_id=be-1"
        )

        assert resp.json()["updated"] == 25
        assert set(resp.json()["notification_ids"]) == {str(event.id) for event in group}
        assert set(resp.json()["unread_notification_ids"]) == {str(event.id) for event in group[1:]}
        assert not NotificationArchiveState.objects.filter(notification_event=other).exists()

        undo = self.client.post(
            f"{base}/unarchive_bulk/",
            {"notification_ids": resp.json()["notification_ids"], "mark_unread": True},
            format="json",
        )

        assert undo.json()["updated"] == 25
        assert not NotificationArchiveState.objects.filter(user=self.user).exists()
        assert not NotificationReadState.objects.filter(notification_event__in=group, user=self.user).exists()

    @parameterized.expand([("keeps_read", False, True), ("restores_unread", True, False)])
    def test_unarchive(self, _name: str, mark_unread: bool, read_after: bool) -> None:
        event = self._create_notification()
        self.client.post(f"/api/environments/{self.team.id}/notifications/{event.id}/archive/")

        resp = self.client.post(
            f"/api/environments/{self.team.id}/notifications/{event.id}/unarchive/",
            {"mark_unread": mark_unread},
            format="json",
        )

        assert resp.status_code == 200
        assert not NotificationArchiveState.objects.filter(notification_event=event, user=self.user).exists()
        assert NotificationReadState.objects.filter(notification_event=event, user=self.user).exists() is read_after

    @parameterized.expand(
        [
            ("detail", "{base}/{id}/archive/", None),
            ("bulk", "{base}/archive_bulk/", "notification_ids"),
            ("all", "{base}/archive_all/", None),
        ]
    )
    def test_archive_marks_notification_read(self, _name, path_template, ids_field):
        event = self._create_notification()
        base = f"/api/environments/{self.team.id}/notifications"
        path = path_template.format(base=base, id=event.id)
        payload = {ids_field: [str(event.id)]} if ids_field else None

        resp = self.client.post(path, payload, format="json") if payload else self.client.post(path)

        assert resp.status_code == 200
        assert NotificationReadState.objects.filter(notification_event=event, user=self.user).exists()

    def test_archived_notification_serializes_as_read(self):
        event = self._create_notification()
        self.client.post(f"/api/environments/{self.team.id}/notifications/{event.id}/archive/")

        resp = self.client.get(f"/api/environments/{self.team.id}/notifications/?archived=true")

        row = next(r for r in resp.json()["results"] if r["id"] == str(event.id))
        assert row["read"] is True
        assert row["read_at"] is not None

    def test_archive_does_not_mark_read_for_another_user(self):
        other_user = User.objects.create_and_join(self.organization, "archiveread@test.com", "password")
        event = self._create_notification()
        NotificationEvent.objects.filter(pk=event.pk).update(resolved_user_ids=[self.user.id, other_user.id])

        self.client.post(f"/api/environments/{self.team.id}/notifications/{event.id}/archive/")

        assert not NotificationReadState.objects.filter(notification_event=event, user=other_user).exists()

    def test_archive_is_per_user(self):
        other_user = User.objects.create_and_join(self.organization, "archiveother@test.com", "password")
        event = self._create_notification()
        NotificationEvent.objects.filter(pk=event.pk).update(resolved_user_ids=[self.user.id, other_user.id])
        self.client.post(f"/api/environments/{self.team.id}/notifications/{event.id}/archive/")

        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.get(f"/api/environments/{self.team.id}/notifications/")
        ids = {r["id"] for r in resp.json()["results"]}
        assert str(event.id) in ids


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
