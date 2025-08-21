from rest_framework import status
from posthog.models import Team

from posthog.test.base import APIBaseTest
from products.llm_analytics.backend.models.datasets import Dataset


class TestDatasetsApi(APIBaseTest):
    def test_can_create_dataset(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Test Dataset", "description": "Test Description", "metadata": {"key": "value"}},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Dataset.objects.count(), 1)
        dataset = Dataset.objects.first()
        assert dataset is not None
        self.assertEqual(dataset.name, "Test Dataset")
        self.assertEqual(dataset.description, "Test Description")
        self.assertEqual(dataset.metadata, {"key": "value"})
        self.assertEqual(dataset.team, self.team)
        self.assertEqual(dataset.created_by, self.user)

    def test_can_retrieve_list_of_datasets(self):
        self.client.force_login(self.user)
        Dataset.objects.create(name="Dataset 1", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Dataset 2", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        dataset_names = [dataset["name"] for dataset in response.data["results"]]
        self.assertIn("Dataset 1", dataset_names)
        self.assertIn("Dataset 2", dataset_names)

    def test_can_get_single_dataset(self):
        self.client.force_login(self.user)
        dataset = Dataset.objects.create(
            name="Test Dataset",
            description="Test Description",
            metadata={"key": "value"},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/{dataset.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Dataset")
        self.assertEqual(response.data["description"], "Test Description")
        self.assertEqual(response.data["metadata"], {"key": "value"})

    def test_can_edit_dataset(self):
        self.client.force_login(self.user)
        dataset = Dataset.objects.create(name="Original Name", team=self.team, created_by=self.user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/datasets/{dataset.id}/",
            {"name": "Updated Name", "description": "Updated Description"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dataset.refresh_from_db()
        self.assertEqual(dataset.name, "Updated Name")
        self.assertEqual(dataset.description, "Updated Description")

    def test_delete_method_returns_405(self):
        self.client.force_login(self.user)
        dataset = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.delete(f"/api/environments/{self.team.id}/datasets/{dataset.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_can_soft_delete_dataset_with_patch(self):
        self.client.force_login(self.user)
        dataset = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.patch(f"/api/environments/{self.team.id}/datasets/{dataset.id}/", {"deleted": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dataset.refresh_from_db()
        self.assertTrue(dataset.deleted)

        # Verify soft-deleted dataset is not returned in list
        list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        self.assertEqual(len(list_response.data["results"]), 0)

    def test_cannot_create_dataset_for_another_team(self):
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        self.client.force_login(self.user)

        response = self.client.post(
            f"/api/environments/{another_team.id}/datasets/", {"name": "Test Dataset", "team": another_team.id}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dataset = Dataset.objects.first()
        assert dataset is not None
        self.assertEqual(dataset.team, self.team)

    def test_cannot_access_another_teams_dataset(self):
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        another_user = self._create_user("another@example.com")
        another_dataset = Dataset.objects.create(
            name="Another Team Dataset", team=another_team, created_by=another_user
        )

        self.client.force_login(self.user)

        # Test GET
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/{another_dataset.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test PATCH
        response = self.client.patch(
            f"/api/environments/{self.team.id}/datasets/{another_dataset.id}/", {"name": "Hacked Name"}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test LIST
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

        # Verify dataset wasn't modified
        another_dataset.refresh_from_db()
        self.assertEqual(another_dataset.name, "Another Team Dataset")

    def test_post_ignores_created_by(self):
        self.client.force_login(self.user)
        another_user = self._create_user("another@example.com")

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {
                "name": "Test Dataset",
                "description": "Test Description",
                "metadata": {"key": "value"},
                "created_by": another_user.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dataset = Dataset.objects.first()
        assert dataset is not None
        self.assertEqual(dataset.created_by, self.user)

    def test_patch_ignores_created_by_and_team(self):
        self.client.force_login(self.user)
        dataset = Dataset.objects.create(name="Original Name", team=self.team, created_by=self.user)
        another_user = self._create_user("another@example.com")
        another_team = Team.objects.create(name="Another Team", organization=self.organization)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/datasets/{dataset.id}/",
            {
                "name": "Updated Name",
                "created_by": another_user.id,
                "team": another_team.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        dataset.refresh_from_db()
        self.assertEqual(dataset.name, "Updated Name")
        self.assertEqual(dataset.created_by, self.user)
        self.assertEqual(dataset.team, self.team)

    def test_can_filter_datasets_by_name(self):
        self.client.force_login(self.user)
        Dataset.objects.create(name="Alpha", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Beta", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"name": "alph"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["name"], "Alpha")

    def test_new_dataset_is_first_in_list(self):
        self.client.force_login(self.user)

        Dataset.objects.create(name="Older", team=self.team, created_by=self.user)

        create_response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Newest"},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_response.data.get("results", [])), 1)
        self.assertEqual(list_response.data["results"][0]["name"], "Newest")
