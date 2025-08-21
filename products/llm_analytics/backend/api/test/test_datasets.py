from rest_framework import status
from posthog.models import Team

from posthog.test.base import APIBaseTest
from products.llm_analytics.backend.models.datasets import Dataset, DatasetItem


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


class TestDatasetItemsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)
        self.dataset = Dataset.objects.create(name="Parent Dataset", team=self.team, created_by=self.user)

    def test_can_create_dataset_item(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {
                "dataset": str(self.dataset.id),
                "input": {"prompt": "Hello"},
                "output": {"completion": "World"},
                "metadata": {"key": "value"},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(DatasetItem.objects.count(), 1)
        item = DatasetItem.objects.first()
        assert item is not None
        self.assertEqual(item.dataset, self.dataset)
        self.assertEqual(item.input, {"prompt": "Hello"})
        self.assertEqual(item.output, {"completion": "World"})
        self.assertEqual(item.metadata, {"key": "value"})
        self.assertEqual(item.team, self.team)
        self.assertEqual(item.created_by, self.user)

    def test_can_retrieve_list_of_dataset_items(self):
        DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)
        DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

    def test_can_get_single_dataset_item(self):
        item = DatasetItem.objects.create(
            dataset=self.dataset,
            team=self.team,
            created_by=self.user,
            input={"a": 1},
            output={"b": 2},
            metadata={"m": 3},
        )

        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["dataset"], str(self.dataset.id))
        self.assertEqual(response.data["input"], {"a": 1})
        self.assertEqual(response.data["output"], {"b": 2})
        self.assertEqual(response.data["metadata"], {"m": 3})

    def test_can_edit_dataset_item(self):
        item = DatasetItem.objects.create(
            dataset=self.dataset, team=self.team, created_by=self.user, input={"x": 1}, output={"y": 2}
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{item.id}/",
            {"input": {"x": 10}, "output": {"y": 20}, "metadata": {"z": 30}},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        item.refresh_from_db()
        self.assertEqual(item.input, {"x": 10})
        self.assertEqual(item.output, {"y": 20})
        self.assertEqual(item.metadata, {"z": 30})

    def test_delete_method_returns_405(self):
        item = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        response = self.client.delete(f"/api/environments/{self.team.id}/dataset_items/{item.id}/")
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_can_soft_delete_dataset_item_with_patch(self):
        item = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        response = self.client.patch(f"/api/environments/{self.team.id}/dataset_items/{item.id}/", {"deleted": True})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        item.refresh_from_db()
        self.assertTrue(item.deleted)

        list_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        self.assertEqual(len(list_response.data["results"]), 0)

    def test_cannot_create_dataset_item_for_another_team(self):
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        # Note: We still create items against the user's current team dataset
        response = self.client.post(
            f"/api/environments/{another_team.id}/dataset_items/",
            {
                "dataset": str(self.dataset.id),
                "input": {"prompt": "Hi"},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = DatasetItem.objects.first()
        assert item is not None
        self.assertEqual(item.team, self.team)

    def test_cannot_access_another_teams_dataset_item(self):
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        another_user = self._create_user("another@example.com")
        another_dataset = Dataset.objects.create(name="Another", team=another_team, created_by=another_user)
        another_item = DatasetItem.objects.create(dataset=another_dataset, team=another_team, created_by=another_user)

        # Test GET
        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/{another_item.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test PATCH
        response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{another_item.id}/",
            {"metadata": {"hack": True}},
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Test LIST
        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

        # Verify item wasn't modified
        another_item.refresh_from_db()
        self.assertIsNone(another_item.metadata)

    def test_post_ignores_created_by(self):
        another_user = self._create_user("another@example.com")
        response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {
                "dataset": str(self.dataset.id),
                "input": {"q": 1},
                "created_by": another_user.id,
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        item = DatasetItem.objects.first()
        assert item is not None
        self.assertEqual(item.created_by, self.user)

    def test_patch_ignores_created_by_and_team(self):
        item = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)
        another_user = self._create_user("another@example.com")
        another_team = Team.objects.create(name="Another Team", organization=self.organization)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{item.id}/",
            {
                "created_by": another_user.id,
                "team": another_team.id,
                "metadata": {"stay": True},
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item.refresh_from_db()
        self.assertEqual(item.created_by, self.user)
        self.assertEqual(item.team, self.team)
        self.assertEqual(item.metadata, {"stay": True})

    def test_can_filter_dataset_items_by_dataset(self):
        dataset_b = Dataset.objects.create(name="B", team=self.team, created_by=self.user)
        item_a = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)
        DatasetItem.objects.create(dataset=dataset_b, team=self.team, created_by=self.user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(self.dataset.id)},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(response.data["results"][0]["id"], str(item_a.id))

    def test_new_dataset_item_is_first_in_list(self):
        DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        create_response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(self.dataset.id), "input": {"n": "new"}},
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        created_id = create_response.data["id"]

        list_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(list_response.data.get("results", [])), 1)
        self.assertEqual(list_response.data["results"][0]["id"], created_id)
