from uuid import uuid4

import pytest
from posthog.test.base import APIBaseTest

from rest_framework import status

from products.uptime.backend.facade import api
from products.uptime.backend.logic import (
    SlugAlreadyTakenError,
    _sanitize_slug,
    create_status_page,
    publish_status_page,
    update_status_page,
)
from products.uptime.backend.models import Monitor, StatusPage
from products.uptime.backend.tests.conftest import UptimeTeamScopedTestMixin


@pytest.mark.django_db
class TestStatusPageLogic:
    def test_create_generates_unique_slug_and_defaults(self, team):
        page = create_status_page(team_id=team.id)
        assert page.title == "Untitled status page"
        assert page.is_published is False
        assert page.monitor_ids == []
        assert page.slug.startswith("untitled-status-page-")

    def test_create_slugs_dont_collide(self, team):
        a = create_status_page(team_id=team.id)
        b = create_status_page(team_id=team.id)
        assert a.slug != b.slug

    def test_update_filters_invalid_monitor_ids(self, team):
        page = create_status_page(team_id=team.id)
        valid_monitor = Monitor.objects.create(team_id=team.id, name="m", url="https://m.io")
        stranger_id = uuid4()

        updated = update_status_page(team_id=team.id, page_id=page.id, monitor_ids=[valid_monitor.id, stranger_id])

        assert updated.monitor_ids == [valid_monitor.id]

    def test_slug_collision_raises(self, team):
        a = create_status_page(team_id=team.id)
        b = create_status_page(team_id=team.id)
        with pytest.raises(SlugAlreadyTakenError):
            update_status_page(team_id=team.id, page_id=b.id, slug=a.slug)

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("My Status Page!", "my-status-page"),
            ("  trim spaces  ", "trim-spaces"),
            ("multiple---dashes", "multiple-dashes"),
            ("UPPER@#case", "upper-case"),
            ("", ""),
        ],
    )
    def test_sanitize_slug(self, raw, expected):
        assert _sanitize_slug(raw) == expected

    def test_publish_sets_published_at_and_flag(self, team):
        page = create_status_page(team_id=team.id)
        published = publish_status_page(team_id=team.id, page_id=page.id)
        assert published.is_published is True
        assert published.published_at is not None


@pytest.mark.django_db
class TestPublicStatusPageView:
    def test_returns_none_for_draft(self, team):
        page = create_status_page(team_id=team.id)
        assert api.get_public_status_page(slug=page.slug) is None

    def test_returns_none_for_unknown_slug(self, team):
        assert api.get_public_status_page(slug="does-not-exist") is None

    def test_returns_published_page_with_monitor_summaries(self, team):
        page = create_status_page(team_id=team.id)
        m = Monitor.objects.create(team_id=team.id, name="m1", url="https://m.io")
        update_status_page(team_id=team.id, page_id=page.id, monitor_ids=[m.id])
        publish_status_page(team_id=team.id, page_id=page.id)

        view = api.get_public_status_page(slug=page.slug)
        assert view is not None
        assert view.title == page.title
        assert [m_summary.id for m_summary in view.monitors] == [m.id]


class TestStatusPageEndpoints(UptimeTeamScopedTestMixin, APIBaseTest):
    """End-to-end smoke tests for the authenticated CRUD + publish/unpublish actions."""

    def _list_url(self) -> str:
        return f"/api/environments/{self.team.id}/uptime/status_pages/"

    def _detail_url(self, page_id: str) -> str:
        return f"/api/environments/{self.team.id}/uptime/status_pages/{page_id}/"

    def test_create_returns_201_and_persists(self) -> None:
        response = self.client.post(self._list_url())
        assert response.status_code == status.HTTP_201_CREATED, response.content
        body = response.json()
        assert body["title"] == "Untitled status page"
        assert StatusPage.objects.filter(team_id=self.team.id, id=body["id"]).exists()

    def test_patch_updates_title(self) -> None:
        page = create_status_page(team_id=self.team.id)
        response = self.client.patch(self._detail_url(str(page.id)), {"title": "PostHog status"}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["title"] == "PostHog status"

    def test_publish_and_unpublish(self) -> None:
        page = create_status_page(team_id=self.team.id)

        published = self.client.post(f"{self._detail_url(str(page.id))}publish/")
        assert published.status_code == status.HTTP_200_OK
        assert published.json()["is_published"] is True

        unpublished = self.client.post(f"{self._detail_url(str(page.id))}unpublish/")
        assert unpublished.status_code == status.HTTP_200_OK
        assert unpublished.json()["is_published"] is False


class TestPublicStatusPageEndpoint(UptimeTeamScopedTestMixin, APIBaseTest):
    def test_published_page_is_publicly_accessible(self) -> None:
        page = create_status_page(team_id=self.team.id)
        publish_status_page(team_id=self.team.id, page_id=page.id)

        self.client.logout()
        response = self.client.get(f"/api/uptime/public_status_pages/{page.slug}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == page.title

    def test_draft_page_returns_404_publicly(self) -> None:
        page = create_status_page(team_id=self.team.id)

        self.client.logout()
        response = self.client.get(f"/api/uptime/public_status_pages/{page.slug}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
