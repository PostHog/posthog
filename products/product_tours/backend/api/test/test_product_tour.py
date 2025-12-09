from posthog.test.base import APIBaseTest

from rest_framework import status

from products.product_tours.backend.models import ProductTour


class TestProductTour(APIBaseTest):
    def test_can_create_product_tour(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Onboarding tour",
                "description": "Welcome new users to the app",
                "content": {
                    "steps": [
                        {
                            "selector": "#dashboard-button",
                            "title": "Welcome!",
                            "description": "Click here to view your dashboard",
                            "position": "bottom",
                        }
                    ]
                },
            },
            format="json",
        )
        response_data = response.json()
        assert response.status_code == status.HTTP_201_CREATED, response_data
        assert ProductTour.objects.filter(id=response_data["id"]).exists()
        assert response_data["name"] == "Onboarding tour"
        assert response_data["created_by"]["id"] == self.user.id

    def test_can_list_product_tours(self):
        ProductTour.objects.create(
            team=self.team,
            name="Tour 1",
            content={"steps": []},
            created_by=self.user,
        )
        ProductTour.objects.create(
            team=self.team,
            name="Tour 2",
            content={"steps": []},
            created_by=self.user,
        )

        response = self.client.get(f"/api/projects/{self.team.id}/product_tours/")
        response_data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert len(response_data["results"]) == 2

    def test_can_update_product_tour(self):
        tour = ProductTour.objects.create(
            team=self.team,
            name="Original name",
            content={"steps": []},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour.id}/",
            data={"name": "Updated name"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Updated name"

    def test_delete_archives_tour(self):
        tour = ProductTour.objects.create(
            team=self.team,
            name="To be archived",
            content={"steps": []},
            created_by=self.user,
        )

        response = self.client.delete(f"/api/projects/{self.team.id}/product_tours/{tour.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Tour should be archived, not deleted
        tour = ProductTour.all_objects.get(id=tour.id)
        assert tour.archived is True

        # Should not appear in normal list
        assert not ProductTour.objects.filter(id=tour.id).exists()
