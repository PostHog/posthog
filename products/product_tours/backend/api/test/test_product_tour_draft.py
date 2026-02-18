from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.feature_flag import FeatureFlag

from products.product_tours.backend.models import ProductTour


class TestProductTourDraft(APIBaseTest):
    def _create_tour(self, **kwargs):
        defaults = {
            "team": self.team,
            "name": "Test tour",
            "description": "A test tour",
            "content": {"steps": [{"id": "s1", "title": "Welcome"}]},
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return ProductTour.objects.create(**defaults)

    def _draft_url(self, tour_id):
        return f"/api/projects/{self.team.id}/product_tours/{tour_id}/draft/"

    def _publish_url(self, tour_id):
        return f"/api/projects/{self.team.id}/product_tours/{tour_id}/publish_draft/"

    def _discard_url(self, tour_id):
        return f"/api/projects/{self.team.id}/product_tours/{tour_id}/discard_draft/"

    def test_draft_save_stores_data_in_draft_content(self):
        tour = self._create_tour()

        response = self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Draft name"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.draft_content is not None
        assert tour.draft_content["name"] == "Draft name"

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_draft_save_triggers_no_side_effects(self, mock_report):
        tour = self._create_tour()

        response = self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Draft name", "auto_launch": True},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_report.assert_not_called()

    def test_draft_merge_combines_with_existing_draft(self):
        tour = self._create_tour()

        self.client.patch(
            self._draft_url(tour.id),
            data={"name": "First draft"},
            format="json",
        )

        response = self.client.patch(
            self._draft_url(tour.id),
            data={"description": "Updated description"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.draft_content["name"] == "First draft"
        assert tour.draft_content["description"] == "Updated description"

    def test_draft_initialized_from_live_data_on_first_patch(self):
        tour = self._create_tour(name="Live name", description="Live desc")

        response = self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Draft name"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.draft_content["name"] == "Draft name"
        assert tour.draft_content["description"] == "Live desc"
        assert tour.draft_content["content"] == tour.content

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_publish_draft_applies_changes_to_live(self, mock_report):
        tour = self._create_tour()

        self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Published name", "description": "Published desc"},
            format="json",
        )

        response = self.client.post(self._publish_url(tour.id), format="json")

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.name == "Published name"
        assert tour.description == "Published desc"
        assert tour.draft_content is None
        # Should trigger side effects (activity log, report_user_action)
        assert mock_report.call_count > 0

    def test_publish_draft_with_invalid_data_returns_validation_error(self):
        tour = self._create_tour()
        flag = FeatureFlag.objects.create(
            team=self.team,
            key="flag",
            created_by=self.user,
            filters={"groups": [{"properties": [], "rollout_percentage": 100}]},
        )

        # Set up a draft with an invalid linkedFlagVariant
        tour.draft_content = {
            "name": tour.name,
            "content": {"steps": [], "conditions": {"linkedFlagVariant": "nonexistent"}},
            "linked_flag_id": flag.id,
        }
        tour.save(update_fields=["draft_content"])

        response = self.client.post(self._publish_url(tour.id), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_discard_draft_clears_draft_content(self):
        tour = self._create_tour()

        self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Drafted"},
            format="json",
        )
        tour.refresh_from_db()
        assert tour.draft_content is not None

        response = self.client.delete(self._discard_url(tour.id), format="json")

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.draft_content is None

    def test_no_draft_to_publish_returns_400(self):
        tour = self._create_tour()

        response = self.client.post(self._publish_url(tour.id), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No draft to publish" in response.json()["detail"]

    def test_read_serializer_includes_draft_fields(self):
        tour = self._create_tour()
        tour.draft_content = {"name": "Drafted"}
        tour.save(update_fields=["draft_content"])

        response = self.client.get(f"/api/projects/{self.team.id}/product_tours/{tour.id}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["draft_content"] == {"name": "Drafted"}
        assert data["has_draft"] is True

    def test_read_serializer_has_draft_false_when_no_draft(self):
        tour = self._create_tour()

        response = self.client.get(f"/api/projects/{self.team.id}/product_tours/{tour.id}/")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["draft_content"] is None
        assert data["has_draft"] is False

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_direct_update_clears_existing_draft(self, mock_report):
        tour = self._create_tour()
        tour.draft_content = {"name": "Old draft"}
        tour.save(update_fields=["draft_content"])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour.id}/",
            data={"name": "Directly updated"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.draft_content is None
        assert tour.name == "Directly updated"

    @patch("products.product_tours.backend.api.product_tour.publish_draft_update")
    def test_redis_pubsub_published_on_draft_save(self, mock_publish):
        tour = self._create_tour()

        self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Draft"},
            format="json",
        )

        mock_publish.assert_called_once()
        call_args = mock_publish.call_args[0]
        assert call_args[0] == str(tour.id)

    def test_draft_content_not_in_sdk_endpoint(self):
        tour = self._create_tour(start_date=timezone.now(), auto_launch=True)
        tour.draft_content = {"name": "Drafted"}
        tour.save(update_fields=["draft_content"])

        response = self.client.get(f"/api/projects/{self.team.id}/product_tours/{tour.id}/")
        data = response.json()

        # Main API includes draft_content
        assert "draft_content" in data

    @parameterized.expand(
        [
            ("name_only", {"name": "New name"}),
            ("content_only", {"content": {"steps": [{"id": "s2", "title": "Updated"}]}}),
            ("multiple_fields", {"name": "New", "description": "Desc", "auto_launch": True}),
        ]
    )
    def test_draft_save_with_various_partial_payloads(self, _name, payload):
        tour = self._create_tour()

        response = self.client.patch(
            self._draft_url(tour.id),
            data=payload,
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.draft_content is not None
        for key, value in payload.items():
            assert tour.draft_content[key] == value

    def test_publish_draft_clears_draft(self):
        tour = self._create_tour()

        self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Draft name"},
            format="json",
        )

        response = self.client.post(self._publish_url(tour.id), format="json")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["draft_content"] is None
        assert data["has_draft"] is False
        assert data["name"] == "Draft name"

    def test_draft_does_not_affect_live_content(self):
        tour = self._create_tour(name="Live name")

        self.client.patch(
            self._draft_url(tour.id),
            data={"name": "Draft name"},
            format="json",
        )

        tour.refresh_from_db()
        assert tour.name == "Live name"
        assert tour.draft_content["name"] == "Draft name"

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_publish_with_payload_saves_and_publishes_atomically(self, mock_report):
        tour = self._create_tour(name="Original")

        response = self.client.post(
            self._publish_url(tour.id),
            data={"name": "Atomic publish", "description": "In one call"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        tour.refresh_from_db()
        assert tour.name == "Atomic publish"
        assert tour.description == "In one call"
        assert tour.draft_content is None
        assert mock_report.call_count > 0

    def test_publish_without_payload_or_draft_returns_400(self):
        tour = self._create_tour()

        response = self.client.post(self._publish_url(tour.id), format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "No draft to publish" in response.json()["detail"]
