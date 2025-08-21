from rest_framework import status

from posthog.test.base import APIBaseTest
from products.llm_observability.models.datasets import Dataset


class TestDatasetsApi(APIBaseTest):
    def test_can_create_dataset(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/api/environments/{self.team.id}/datasets/",
            {"name": "Test Dataset", "description": "Test Description", "metadata": {"key": "value"}},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Dataset.objects.count(), 1)
        self.assertEqual(Dataset.objects.first().name, "Test Dataset")
        self.assertEqual(Dataset.objects.first().description, "Test Description")
        self.assertEqual(Dataset.objects.first().metadata, {"key": "value"})
        self.assertEqual(Dataset.objects.first().team, self.team)
        self.assertEqual(Dataset.objects.first().created_by, self.user)
