from unittest.mock import patch

from rest_framework import status

from posthog.clickhouse.client import sync_execute
from posthog.models import Organization, Team
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.user import User
from posthog.models.utils import generate_random_token_personal
from posthog.test.base import APIBaseTest
from products.editor.backend.chunking.types import Chunk
from products.editor.backend.models.codebase import Codebase


class TestCodebaseSync(APIBaseTest):
    def test_create_codebase(self):
        """Creates a codebase and sets the user and team as the owner."""
        response = self.client.post(f"/api/projects/@current/codebases/")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Codebase.objects.count(), 1)
        codebase: Codebase = Codebase.objects.first()
        self.assertEqual(codebase.team, self.team)
        self.assertEqual(codebase.user, self.user)

    def test_create_codebase_with_body(self):
        """Must ignore body params if provided."""
        response = self.client.post(f"/api/projects/@current/codebases/", {"team": 100, "user": 100})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Codebase.objects.count(), 1)
        codebase: Codebase = Codebase.objects.first()
        self.assertEqual(codebase.team, self.team)
        self.assertEqual(codebase.user, self.user)

    def test_must_not_create_codebase_for_another_team(self):
        """Must not create a codebase for another team."""
        org2 = Organization.objects.create(name="Org 2")
        team2 = Team.objects.create(name="Team 2", organization=org2)
        response = self.client.post(f"/api/projects/{team2.id}/codebases/", {"team": 100, "user": 100})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_access_scoped_to_user(self):
        """User can only access their own codebases."""
        other_user = User.objects.create_and_join(self.organization, "other@posthog.com", "password", "Other")
        other_codebase = Codebase.objects.create(team=self.team, user=other_user)
        response = self.client.patch(
            f"/api/projects/@current/codebases/{other_codebase.id}/sync/",
            {
                "branch": "main",
                "tree": [],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(
            f"/api/projects/@current/codebases/{other_codebase.id}/upload_artifact/",
            {
                "id": "file1",
                "type": "file",
                "extension": "py",
                "content": "print('Hello, world!')",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch(
        "products.editor.backend.tasks.chunk_and_embed",
        return_value=[[Chunk(text="test", line_start=0, line_end=10, context=None, content="test"), [0.1, 0.2, 0.3]]],
    )
    def test_basic_sync(self, chunk_and_embed_mock):
        """Should retrieve the existing ClickHouse records and return all leaf nodes in diverging_nodes."""
        codebase = Codebase.objects.create(team=self.team, user=self.user)
        response = self.client.patch(
            f"/api/projects/@current/codebases/{codebase.id}/sync/",
            {
                "branch": "main",
                "tree": [
                    {
                        "id": "root",
                        "type": "dir",
                    },
                    {
                        "id": "file1",
                        "type": "file",
                        "parent_id": "root",
                    },
                    {
                        "id": "file2",
                        "type": "file",
                        "parent_id": "root",
                    },
                ],
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["synced"])
        self.assertCountEqual(response.data["diverging_files"], ["file1", "file2"])

        response = self.client.post(
            f"/api/projects/@current/codebases/{codebase.id}/upload_artifact/",
            {
                "id": "file1",
                "path": "obfuscated_path_1",
                "extension": "py",
                "content": "print('Hello, world!')",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(chunk_and_embed_mock.call_count, 1)

        response = self.client.post(
            f"/api/projects/@current/codebases/{codebase.id}/upload_artifact/",
            {
                "id": "file2",
                "path": "obfuscated_path_2",
                "extension": "py",
                "content": "four = 2 + 2",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(chunk_and_embed_mock.call_count, 2)

        res = sync_execute(
            "SELECT * FROM codebase_embeddings WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
            team_id=self.team.id,
        )
        self.assertEqual(len(res), 2)

    @patch(
        "products.editor.backend.tasks.chunk_and_embed",
        return_value=[[Chunk(text="test", line_start=0, line_end=10, context=None, content="test"), [0.1, 0.2, 0.3]]],
    )
    def test_codebase_sync_with_personal_api_key(self, chunk_and_embed_mock):
        """Test that CodebaseSyncViewset endpoints are accessible using a personal API key."""
        # Create a personal API key with full access
        api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Test CodebaseSync Key",
            user=self.user,
            secure_value=hash_key_value(api_key_value),
            scopes=["*"],  # Full access scope
        )

        # Create a codebase first
        response = self.client.post(
            f"/api/projects/@current/codebases/", {}, HTTP_AUTHORIZATION=f"Bearer {api_key_value}"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        codebase_id = response.json()["id"]

        # Test sync endpoint with the API key
        response = self.client.patch(
            f"/api/projects/@current/codebases/{codebase_id}/sync/",
            {
                "branch": "main",
                "tree": [
                    {
                        "id": "root",
                        "type": "dir",
                    },
                    {
                        "id": "file1",
                        "type": "file",
                        "parent_id": "root",
                    },
                ],
            },
            HTTP_AUTHORIZATION=f"Bearer {api_key_value}",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["synced"])
        self.assertCountEqual(response.json()["diverging_files"], ["file1"])

        # Test upload artifact endpoint with the API key
        response = self.client.post(
            f"/api/projects/@current/codebases/{codebase_id}/upload_artifact/",
            {
                "id": "file1",
                "path": "path/to/file.py",
                "extension": "py",
                "content": "print('API key test')",
            },
            HTTP_AUTHORIZATION=f"Bearer {api_key_value}",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(chunk_and_embed_mock.call_count, 1)

        # Test with scoped API key (limited to just this team)
        scoped_api_key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Scoped CodebaseSync Key",
            user=self.user,
            secure_value=hash_key_value(scoped_api_key_value),
            scopes=["*"],
            scoped_teams=[self.team.id],
        )

        # Create another codebase with the scoped key
        response = self.client.post(
            f"/api/projects/{self.team.id}/codebases/", {}, HTTP_AUTHORIZATION=f"Bearer {scoped_api_key_value}"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # Create a different organization and team
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(name="Other Team", organization=other_org)

        # Test that the scoped key can't access endpoints for other teams
        response = self.client.post(
            f"/api/projects/{other_team.id}/codebases/", {}, HTTP_AUTHORIZATION=f"Bearer {scoped_api_key_value}"
        )
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])
