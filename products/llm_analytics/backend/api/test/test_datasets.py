from uuid import uuid4

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import Organization, Project, Team, User

from products.llm_analytics.backend.models.datasets import Dataset, DatasetItem


def _setup_team():
    org = Organization.objects.create(name="test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=str(uuid4()),
        test_account_filters=[
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ],
        has_completed_onboarding_for={"product_analytics": True},
    )
    User.objects.create_and_join(org, "test-datasets@posthog.com", "testpassword123")
    return team


class TestDatasetsApi(APIBaseTest):
    def test_unauthenticated_user_cannot_access_datasets(self):
        self.client.logout()
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_can_create_dataset(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Test Dataset", "description": "Test Description", "metadata": {"key": "value"}},
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert Dataset.objects.count() == 1
        dataset = Dataset.objects.first()
        assert dataset is not None
        assert dataset.name == "Test Dataset"
        assert dataset.description == "Test Description"
        assert dataset.metadata == {"key": "value"}
        assert dataset.team == self.team
        assert dataset.created_by == self.user

    def test_can_retrieve_list_of_datasets(self):
        Dataset.objects.create(name="Dataset 1", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Dataset 2", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

        dataset_names = [dataset["name"] for dataset in response.data["results"]]
        assert "Dataset 1" in dataset_names
        assert "Dataset 2" in dataset_names

    def test_can_get_single_dataset(self):
        dataset = Dataset.objects.create(
            name="Test Dataset",
            description="Test Description",
            metadata={"key": "value"},
            team=self.team,
            created_by=self.user,
        )

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/{dataset.id}/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["name"] == "Test Dataset"
        assert response.data["description"] == "Test Description"
        assert response.data["metadata"] == {"key": "value"}

    def test_can_edit_dataset(self):
        dataset = Dataset.objects.create(name="Original Name", team=self.team, created_by=self.user)

        response = self.client.patch(
            f"/api/environments/{self.team.id}/datasets/{dataset.id}/",
            {"name": "Updated Name", "description": "Updated Description"},
        )
        assert response.status_code == status.HTTP_200_OK

        dataset.refresh_from_db()
        assert dataset.name == "Updated Name"
        assert dataset.description == "Updated Description"

    def test_delete_method_returns_405(self):
        dataset = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.delete(f"/api/environments/{self.team.id}/datasets/{dataset.id}/")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_can_soft_delete_dataset_with_patch(self):
        dataset = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.patch(f"/api/environments/{self.team.id}/datasets/{dataset.id}/", {"deleted": True})
        assert response.status_code == status.HTTP_200_OK

        dataset.refresh_from_db()
        assert dataset.deleted

        # Verify soft-deleted dataset is not returned in list
        list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert len(list_response.data["results"]) == 0

    def test_can_undelete_dataset_with_patch(self):
        dataset = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        # First soft delete the dataset
        response = self.client.patch(f"/api/environments/{self.team.id}/datasets/{dataset.id}/", {"deleted": True})
        assert response.status_code == status.HTTP_200_OK

        dataset.refresh_from_db()
        assert dataset.deleted

        # Verify it's not in the list
        list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert len(list_response.data["results"]) == 0

        # Now undelete it
        response = self.client.patch(f"/api/environments/{self.team.id}/datasets/{dataset.id}/", {"deleted": False})
        assert response.status_code == status.HTTP_200_OK

        dataset.refresh_from_db()
        assert not dataset.deleted

        # Verify it's back in the list
        list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert len(list_response.data["results"]) == 1
        assert list_response.data["results"][0]["id"] == str(dataset.id)

    def test_deleted_dataset_can_be_retrieved_for_updates(self):
        dataset = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        # Soft delete the dataset
        response = self.client.patch(f"/api/environments/{self.team.id}/datasets/{dataset.id}/", {"deleted": True})
        assert response.status_code == status.HTTP_200_OK

        # Should not be able to retrieve via GET
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/{dataset.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # But should be able to update it via PATCH (which allows undeleting)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/datasets/{dataset.id}/", {"name": "Updated Name"}
        )
        assert response.status_code == status.HTTP_200_OK

        dataset.refresh_from_db()
        assert dataset.name == "Updated Name"
        assert dataset.deleted  # Still deleted unless explicitly undeleted

    def test_cannot_create_dataset_for_another_team(self):
        another_team = _setup_team()

        response = self.client.post(
            f"/api/environments/{another_team.id}/datasets/", {"name": "Test Dataset", "team": another_team.id}
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/", {"name": "Test Dataset", "team": another_team.id}
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["team"] == self.team.id

    def test_cannot_access_another_teams_dataset(self):
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        another_user = self._create_user("another@example.com")
        another_dataset = Dataset.objects.create(
            name="Another Team Dataset", team=another_team, created_by=another_user
        )

        # Test GET
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/{another_dataset.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test PATCH
        response = self.client.patch(
            f"/api/environments/{self.team.id}/datasets/{another_dataset.id}/", {"name": "Hacked Name"}
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test LIST
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

        # Verify dataset wasn't modified
        another_dataset.refresh_from_db()
        assert another_dataset.name == "Another Team Dataset"

    def test_post_ignores_created_by(self):
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
        assert response.status_code == status.HTTP_201_CREATED
        dataset = Dataset.objects.first()
        assert dataset is not None
        assert dataset.created_by == self.user

    def test_patch_ignores_created_by_and_team(self):
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
        assert response.status_code == status.HTTP_200_OK

        dataset.refresh_from_db()
        assert dataset.name == "Updated Name"
        assert dataset.created_by == self.user
        assert dataset.team == self.team

    def test_new_dataset_is_first_in_list(self):
        Dataset.objects.create(name="Older", team=self.team, created_by=self.user)

        create_response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Newest"},
        )
        assert create_response.status_code == status.HTTP_201_CREATED

        list_response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert list_response.status_code == status.HTTP_200_OK
        assert len(list_response.data.get("results", [])) >= 1
        assert list_response.data["results"][0]["name"] == "Newest"

    def test_order_by_created_at_desc(self):
        # Create datasets with small time gaps to ensure different created_at values
        Dataset.objects.create(name="First", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Second", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Third", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"order_by": "-created_at"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3

        # Should be ordered by newest first
        assert results[0]["name"] == "Third"
        assert results[1]["name"] == "Second"
        assert results[2]["name"] == "First"

    def test_order_by_created_at_asc(self):
        Dataset.objects.create(name="First", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Second", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Third", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"order_by": "created_at"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3

        # Should be ordered by oldest first
        assert results[0]["name"] == "First"
        assert results[1]["name"] == "Second"
        assert results[2]["name"] == "Third"

    def test_order_by_updated_at_desc(self):
        # Create datasets
        first = Dataset.objects.create(name="First", team=self.team, created_by=self.user)
        second = Dataset.objects.create(name="Second", team=self.team, created_by=self.user)
        third = Dataset.objects.create(name="Third", team=self.team, created_by=self.user)

        # Update them in reverse order to change updated_at
        third.description = "Updated third"
        third.save()
        first.description = "Updated first"
        first.save()
        second.description = "Updated second"
        second.save()

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"order_by": "-updated_at"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3

        # Should be ordered by most recently updated first
        assert results[0]["name"] == "Second"
        assert results[1]["name"] == "First"
        assert results[2]["name"] == "Third"

    def test_order_by_updated_at_asc(self):
        first = Dataset.objects.create(name="First", team=self.team, created_by=self.user)
        second = Dataset.objects.create(name="Second", team=self.team, created_by=self.user)
        third = Dataset.objects.create(name="Third", team=self.team, created_by=self.user)

        # Update them in specific order
        second.description = "Updated second"
        second.save()
        third.description = "Updated third"
        third.save()
        first.description = "Updated first"
        first.save()

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"order_by": "updated_at"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 3

        # Should be ordered by least recently updated first
        assert results[0]["name"] == "Second"
        assert results[1]["name"] == "Third"
        assert results[2]["name"] == "First"

    def test_invalid_filter_raises(self):
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"order_by": "invalid_field"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_no_order_by_defaults_to_created_at_desc(self):
        Dataset.objects.create(name="First", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Second", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/")
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2

        # Should default to newest first (created_at desc)
        assert results[0]["name"] == "Second"
        assert results[1]["name"] == "First"

    def test_search_by_name(self):
        Dataset.objects.create(name="Training Dataset", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Validation Data", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "training"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Training Dataset"

    def test_search_by_description(self):
        Dataset.objects.create(
            name="Dataset A", description="Machine learning training data", team=self.team, created_by=self.user
        )
        Dataset.objects.create(
            name="Dataset B", description="Test validation set", team=self.team, created_by=self.user
        )
        Dataset.objects.create(name="Dataset C", description="Production dataset", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "training"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Dataset A"

    def test_search_by_metadata(self):
        Dataset.objects.create(
            name="Dataset 1", metadata={"type": "training", "version": "1.0"}, team=self.team, created_by=self.user
        )
        Dataset.objects.create(
            name="Dataset 2",
            metadata={"type": "test", "environment": "production"},
            team=self.team,
            created_by=self.user,
        )
        Dataset.objects.create(
            name="Dataset 3", metadata={"category": "validation"}, team=self.team, created_by=self.user
        )

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "production"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["name"] == "Dataset 2"

    def test_search_case_insensitive(self):
        Dataset.objects.create(name="Training Dataset", team=self.team, created_by=self.user)
        Dataset.objects.create(name="test dataset", team=self.team, created_by=self.user)

        # Test uppercase search
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "TRAINING"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "Training Dataset"

        # Test lowercase search
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "test"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["name"] == "test dataset"

    def test_search_multiple_matches(self):
        Dataset.objects.create(name="ML Training Set", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Training Data V2", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Validation Set", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "training"})
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2

        names = [result["name"] for result in results]
        assert "ML Training Set" in names
        assert "Training Data V2" in names

    def test_search_no_matches(self):
        Dataset.objects.create(name="Training Dataset", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": "nonexistent"})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

    def test_search_empty_string(self):
        Dataset.objects.create(name="Dataset 1", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Dataset 2", team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"search": ""})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

    def test_search_with_order_by_created_at_desc(self):
        Dataset.objects.create(name="Training Alpha", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Training Beta", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/datasets/", {"search": "training", "order_by": "-created_at"}
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2

        # Should be ordered by newest first within search results
        assert results[0]["name"] == "Training Beta"
        assert results[1]["name"] == "Training Alpha"

    def test_search_with_order_by_created_at_asc(self):
        Dataset.objects.create(name="Training Alpha", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Training Beta", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/datasets/", {"search": "training", "order_by": "created_at"}
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2

        # Should be ordered by oldest first within search results
        assert results[0]["name"] == "Training Alpha"
        assert results[1]["name"] == "Training Beta"

    def test_search_with_order_by_updated_at(self):
        first = Dataset.objects.create(name="Training Alpha", description="First", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Training Beta", description="Second", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        # Update second dataset to make it more recently updated
        first.description = "Updated first"
        first.save()

        response = self.client.get(
            f"/api/environments/{self.team.id}/datasets/", {"search": "training", "order_by": "-updated_at"}
        )
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 2

        # Should be ordered by most recently updated first
        assert results[0]["name"] == "Training Alpha"
        assert results[1]["name"] == "Training Beta"

    def test_can_filter_datasets_by_array_of_ids(self):
        item1 = Dataset.objects.create(name="Training Alpha", description="First", team=self.team, created_by=self.user)
        Dataset.objects.create(name="Training Beta", description="Second", team=self.team, created_by=self.user)
        item3 = Dataset.objects.create(name="Test Dataset", team=self.team, created_by=self.user)

        # Test filtering by a single id
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"id__in": str(item1.id)})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["id"] == str(item1.id)

        # Test filtering by multiple ids
        response = self.client.get(
            f"/api/environments/{self.team.id}/datasets/", {"id__in": ",".join([str(item1.id), str(item3.id)])}
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2
        returned_ids = {result["id"] for result in response.data["results"]}
        assert returned_ids == {str(item1.id), str(item3.id)}

        # Test that non-existent ids return empty results
        fake_id = uuid4()
        response = self.client.get(f"/api/environments/{self.team.id}/datasets/", {"id__in": str(fake_id)})
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0


class TestDatasetItemsApi(APIBaseTest):
    def setUp(self):
        super().setUp()
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
        assert response.status_code == status.HTTP_201_CREATED
        assert DatasetItem.objects.count() == 1
        item = DatasetItem.objects.first()
        assert item is not None
        assert item.dataset == self.dataset
        assert item.input == {"prompt": "Hello"}
        assert item.output == {"completion": "World"}
        assert item.metadata == {"key": "value"}
        assert item.team == self.team
        assert item.created_by == self.user

    def test_can_retrieve_list_of_dataset_items(self):
        DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)
        DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 2

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
        assert response.status_code == status.HTTP_200_OK
        assert response.data["dataset"] == self.dataset.id
        assert response.data["input"] == {"a": 1}
        assert response.data["output"] == {"b": 2}
        assert response.data["metadata"] == {"m": 3}

    def test_can_edit_dataset_item(self):
        item = DatasetItem.objects.create(
            dataset=self.dataset, team=self.team, created_by=self.user, input={"x": 1}, output={"y": 2}
        )

        response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{item.id}/",
            {"input": {"x": 10}, "output": {"y": 20}, "metadata": {"z": 30}},
        )
        assert response.status_code == status.HTTP_200_OK

        item.refresh_from_db()
        assert item.input == {"x": 10}
        assert item.output == {"y": 20}
        assert item.metadata == {"z": 30}

    def test_delete_method_returns_405(self):
        item = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        response = self.client.delete(f"/api/environments/{self.team.id}/dataset_items/{item.id}/")
        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_can_soft_delete_dataset_item_with_patch(self):
        item = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        response = self.client.patch(f"/api/environments/{self.team.id}/dataset_items/{item.id}/", {"deleted": True})
        assert response.status_code == status.HTTP_200_OK

        item.refresh_from_db()
        assert item.deleted

        list_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        assert len(list_response.data["results"]) == 0

    def test_can_undelete_dataset_item_with_patch(self):
        item = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        # First soft delete the item
        response = self.client.patch(f"/api/environments/{self.team.id}/dataset_items/{item.id}/", {"deleted": True})
        assert response.status_code == status.HTTP_200_OK

        item.refresh_from_db()
        assert item.deleted

        # Verify it's not in the list
        list_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        assert len(list_response.data["results"]) == 0

        # Now undelete it
        response = self.client.patch(f"/api/environments/{self.team.id}/dataset_items/{item.id}/", {"deleted": False})
        assert response.status_code == status.HTTP_200_OK

        item.refresh_from_db()
        assert not item.deleted

        # Verify it's back in the list
        list_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        assert len(list_response.data["results"]) == 1
        assert list_response.data["results"][0]["id"] == str(item.id)

    def test_deleted_dataset_item_can_be_retrieved_for_updates(self):
        item = DatasetItem.objects.create(
            dataset=self.dataset,
            team=self.team,
            created_by=self.user,
            input={"prompt": "original"},
            output={"response": "original"},
        )

        # Soft delete the item
        response = self.client.patch(f"/api/environments/{self.team.id}/dataset_items/{item.id}/", {"deleted": True})
        assert response.status_code == status.HTTP_200_OK

        # Should not be able to retrieve via GET
        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/{item.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # But should be able to update it via PATCH (which allows undeleting)
        response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{item.id}/", {"input": {"prompt": "updated"}}
        )
        assert response.status_code == status.HTTP_200_OK

        item.refresh_from_db()
        assert item.input == {"prompt": "updated"}
        assert item.deleted  # Still deleted unless explicitly undeleted

    def test_cannot_create_dataset_item_for_another_team(self):
        another_team = _setup_team()

        # Note: We still create items against the user's current team dataset
        response = self.client.post(
            f"/api/environments/{another_team.id}/dataset_items/",
            {
                "dataset": str(self.dataset.id),
                "input": {"prompt": "Hi"},
            },
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {
                "dataset": str(self.dataset.id),
                "input": {"prompt": "Hi"},
                "team": another_team.id,
            },
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["team"] == self.team.id

    def test_cannot_access_another_teams_dataset_item(self):
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        another_user = self._create_user("another@example.com")
        another_dataset = Dataset.objects.create(name="Another", team=another_team, created_by=another_user)
        another_item = DatasetItem.objects.create(dataset=another_dataset, team=another_team, created_by=another_user)

        # Test GET
        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/{another_item.id}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test PATCH
        response = self.client.patch(
            f"/api/environments/{self.team.id}/dataset_items/{another_item.id}/",
            {"metadata": {"hack": True}},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Test LIST
        response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 0

        # Verify item wasn't modified
        another_item.refresh_from_db()
        assert another_item.metadata is None

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
        assert response.status_code == status.HTTP_201_CREATED
        item = DatasetItem.objects.first()
        assert item is not None
        assert item.created_by == self.user

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
        assert response.status_code == status.HTTP_200_OK
        item.refresh_from_db()
        assert item.created_by == self.user
        assert item.team == self.team
        assert item.metadata == {"stay": True}

    def test_can_filter_dataset_items_by_dataset(self):
        dataset_b = Dataset.objects.create(name="B", team=self.team, created_by=self.user)
        item_a = DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)
        DatasetItem.objects.create(dataset=dataset_b, team=self.team, created_by=self.user)

        response = self.client.get(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(self.dataset.id)},
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["id"] == str(item_a.id)

    def test_new_dataset_item_is_first_in_list(self):
        DatasetItem.objects.create(dataset=self.dataset, team=self.team, created_by=self.user)

        create_response = self.client.post(
            f"/api/environments/{self.team.id}/dataset_items/",
            {"dataset": str(self.dataset.id), "input": {"n": "new"}},
        )
        assert create_response.status_code == status.HTTP_201_CREATED
        created_id = create_response.data["id"]

        list_response = self.client.get(f"/api/environments/{self.team.id}/dataset_items/")
        assert list_response.status_code == status.HTTP_200_OK
        assert len(list_response.data.get("results", [])) >= 1
        assert list_response.data["results"][0]["id"] == created_id
