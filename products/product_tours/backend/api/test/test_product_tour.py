from posthog.test.base import APIBaseTest

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.remote_config import RemoteConfig

from products.product_tours.backend.models import ProductTour


class TestProductToursRemoved(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.tour = ProductTour.objects.create(
            team=self.team, name="Active tour", content={"steps": []}, start_date=timezone.now()
        )

    @parameterized.expand(
        [
            ("list", "get", ""),
            ("create", "post", ""),
            ("retrieve", "get", "{id}/"),
            ("update", "patch", "{id}/"),
            ("publish_draft", "post", "{id}/publish_draft/"),
        ]
    )
    def test_project_api_is_gone(self, _name, method, path):
        url = f"/api/projects/{self.team.id}/product_tours/" + path.format(id=self.tour.id)
        response = getattr(self.client, method)(url, data={"name": "New tour"}, format="json")
        assert response.status_code == status.HTTP_410_GONE, response.json()

    def test_sdk_endpoint_returns_no_tours(self):
        response = self.client.get(f"/api/product_tours/?token={self.team.api_token}")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"product_tours": []}

    def test_remote_config_reports_tours_off_for_opted_in_team(self):
        self.team.product_tours_opt_in = True
        self.team.save()
        assert RemoteConfig(team=self.team).build_config()["productTours"] is False
