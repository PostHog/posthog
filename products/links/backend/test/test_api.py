from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

import structlog
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.links.backend.models import Link

logger = structlog.get_logger(__name__)


class TestLink(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_create_link_success(self):
        data = {
            "redirect_url": "https://example.com",
            "short_link_domain": "phog.gg",
            "short_code": "test123",
            "description": "Test link",
        }
        response = self.client.post(
            f"/api/projects/{self.team.id}/links",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["short_code"], data["short_code"])
        self.assertEqual(response.json()["created_by"]["id"], self.user.pk)

    @parameterized.expand(["post", "put", "patch"])
    def test_write_rejects_invalid_domain(self, method: str):
        link = Link.objects.create(
            team=self.team,
            redirect_url="https://example.com",
            short_link_domain="phog.gg",
            short_code="test123",
            created_by=self.user,
        )
        data = {
            "redirect_url": "https://example.com",
            "short_link_domain": "invalid.com",
            "short_code": "test456",
            "description": "Test link",
        }
        url = f"/api/projects/{self.team.id}/links"
        if method != "post":
            url = f"{url}/{link.id}"

        response = getattr(self.client, method)(url, data=data)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        json_response = str(response.json())
        self.assertIn("short_link_domain", json_response)
        self.assertIn("Only phog.gg is allowed as a short link domain", json_response)
        link.refresh_from_db()
        self.assertEqual(link.short_link_domain, "phog.gg")

    def test_list_links(self):
        # Create a link first
        link = Link.objects.create(
            team=self.team,
            redirect_url="https://example.com",
            short_link_domain="phog.gg",
            short_code="test123",
            description="Test link",
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/links")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["results"][0]["short_code"], link.short_code)

    def test_retrieve_link(self):
        link = Link.objects.create(
            team=self.team,
            redirect_url="https://example.com",
            short_link_domain="phog.gg",
            short_code="test123",
            description="Test link",
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/links/{link.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["short_code"], link.short_code)

    def test_update_link(self):
        link = Link.objects.create(
            team=self.team,
            redirect_url="https://example.com",
            short_link_domain="phog.gg",
            short_code="test123",
            description="Test link",
            created_by=self.user,
        )

        data = {
            "redirect_url": "https://updated.com",
            "short_link_domain": "phog.gg",
            "short_code": link.short_code,
            "description": "Updated link",
        }

        response = self.client.patch(
            f"/api/projects/{self.team.id}/links/{link.id}",
            data=data,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["redirect_url"], data["redirect_url"])

    def test_delete_link(self):
        link = Link.objects.create(
            team=self.team,
            redirect_url="https://example.com",
            short_link_domain="phog.gg",
            short_code="test123",
            description="Test link",
            created_by=self.user,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/links/{link.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Link.objects.filter(id=link.id).exists())

    def test_unauthorized_access(self):
        # Create a new client without authentication
        client = APIClient()
        response = client.get(f"/api/projects/{self.team.id}/links")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_link_team_isolation(self):
        # Create a second team
        team2 = Team.objects.create(organization=self.organization, name="Team 2")

        # Create links in both teams
        link1 = Link.objects.create(
            team=self.team,
            redirect_url="https://example1.com",
            short_link_domain="phog.gg",
            short_code="test1",
            created_by=self.user,
        )
        link2 = Link.objects.create(
            team=team2,
            redirect_url="https://example2.com",
            short_link_domain="phog.gg",
            short_code="test2",
            created_by=self.user,
        )

        # Should only see links from current team
        response = self.client.get(f"/api/projects/{self.team.id}/links")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(str(response.json()["results"][0]["id"]), str(link1.id))

        # The project in the URL decides, not the caller's current team
        response = self.client.get(f"/api/projects/{team2.id}/links")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(str(response.json()["results"][0]["id"]), str(link2.id))

    def test_project_in_another_org_is_refused(self):
        foreign_org = Organization.objects.create(name="Foreign org")
        foreign_team = Team.objects.create(organization=foreign_org, name="Foreign team")
        foreign_link = Link.objects.create(
            team=foreign_team,
            redirect_url="https://foreign.example.com",
            short_link_domain="phog.gg",
            short_code="foreign1",
        )

        response = self.client.get(f"/api/projects/{foreign_team.id}/links")

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn(str(foreign_link.id), response.content.decode())
        self.assertNotIn("foreign.example.com", response.content.decode())

    def test_create_link_in_specific_folder(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/links",
            data={
                "redirect_url": "https://example.com",
                "short_link_domain": "phog.gg",
                "short_code": "test123",
                "description": "Test link",
                "_create_in_folder": "Special Folder/Links",
            },
            format="json",
        )
        assert response.status_code == 201, response.json()

        link_id = response.json()["id"]
        assert link_id is not None

        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(link_id), type="link").first()
        assert fs_entry is not None, "A FileSystem entry was not created for this Link."
        assert "Special Folder/Links" in fs_entry.path, (
            f"Expected path to include 'Special Folder/Links', got '{fs_entry.path}'."
        )
