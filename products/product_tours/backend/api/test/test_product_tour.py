from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from rest_framework import status

from posthog.models.feature_flag import FeatureFlag
from posthog.models.surveys.survey import Survey

from products.product_tours.backend.constants import ProductTourEventName
from products.product_tours.backend.models import ProductTour


class TestProductTour(APIBaseTest):
    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_can_create_product_tour(self, mock_report):
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

        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args[0][0] == self.user
        assert call_args[0][1] == ProductTourEventName.CREATED
        assert call_args[0][2]["tour_id"] == response_data["id"]
        assert call_args[0][2]["tour_name"] == "Onboarding tour"
        assert call_args[0][2]["creation_context"] == "app"

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

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_can_update_product_tour(self, mock_report):
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

        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args[0][1] == ProductTourEventName.UPDATED
        assert call_args[0][2]["tour_name"] == "Updated name"

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_delete_archives_tour(self, mock_report):
        tour = ProductTour.objects.create(
            team=self.team,
            name="To be archived",
            content={"steps": []},
            created_by=self.user,
        )
        tour_id = str(tour.id)

        response = self.client.delete(f"/api/projects/{self.team.id}/product_tours/{tour.id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Tour should be archived, not deleted
        tour = ProductTour.all_objects.get(id=tour_id)
        assert tour.archived

        # Should not appear in normal list
        assert not ProductTour.objects.filter(id=tour_id).exists()

        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args[0][1] == ProductTourEventName.DELETED
        assert call_args[0][2]["tour_id"] == tour_id

    def test_announcement_cannot_have_multiple_steps(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Invalid announcement",
                "content": {
                    "type": "announcement",
                    "steps": [
                        {"id": "step-1", "type": "modal", "content": {}},
                        {"id": "step-2", "type": "modal", "content": {}},
                    ],
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Announcements must have exactly 1 step." in str(response.json())

    def test_announcement_with_single_step_is_valid(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Valid announcement",
                "content": {
                    "type": "announcement",
                    "steps": [
                        {"id": "step-1", "type": "modal", "content": {}},
                    ],
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_regular_tour_can_have_multiple_steps(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Multi-step tour",
                "content": {
                    "steps": [
                        {"id": "step-1", "selector": "#btn1", "content": {}},
                        {"id": "step-2", "selector": "#btn2", "content": {}},
                        {"id": "step-3", "selector": "#btn3", "content": {}},
                    ],
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_update_to_announcement_with_multiple_steps_fails(self):
        tour = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Tour",
                "content": {"steps": [{"id": "1", "type": "modal"}, {"id": "2", "type": "modal"}]},
            },
            format="json",
        ).json()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour['id']}/",
            data={"content": {"type": "announcement", "steps": tour["content"]["steps"]}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_launched_event_captured_when_start_date_set(self, mock_report):
        tour = ProductTour.objects.create(
            team=self.team,
            name="Tour to launch",
            content={"steps": []},
            created_by=self.user,
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour.id}/",
            data={"start_date": timezone.now().isoformat()},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # Should have two calls: UPDATED and LAUNCHED
        assert mock_report.call_count == 2
        call_events = [call[0][1] for call in mock_report.call_args_list]
        assert ProductTourEventName.UPDATED in call_events
        assert ProductTourEventName.LAUNCHED in call_events

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_stopped_event_captured_when_end_date_set(self, mock_report):
        tour = ProductTour.objects.create(
            team=self.team,
            name="Running tour",
            content={"steps": []},
            created_by=self.user,
            start_date=timezone.now(),
        )

        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour.id}/",
            data={"end_date": timezone.now().isoformat()},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # Should have two calls: UPDATED and STOPPED
        assert mock_report.call_count == 2
        call_events = [call[0][1] for call in mock_report.call_args_list]
        assert ProductTourEventName.UPDATED in call_events
        assert ProductTourEventName.STOPPED in call_events

    @patch("products.product_tours.backend.api.product_tour.report_user_action")
    def test_creation_context_from_toolbar(self, mock_report):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Toolbar tour",
                "content": {"steps": []},
                "creation_context": "toolbar",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED

        mock_report.assert_called_once()
        call_args = mock_report.call_args
        assert call_args[0][2]["creation_context"] == "toolbar"


class TestProductTourAnalyticsMetadata(APIBaseTest):
    @parameterized.expand(
        [
            # (content, expected_metadata_subset)
            (
                {"steps": []},
                {"step_count": 0, "has_url_condition": False, "has_selector_condition": False},
            ),
            (
                {"steps": [{"id": "1"}], "conditions": {"url": "https://example.com"}},
                {"step_count": 1, "has_url_condition": True},
            ),
            (
                {"steps": [], "conditions": {"selector": "#my-element"}},
                {"has_selector_condition": True},
            ),
            (
                {"steps": [], "conditions": {"actions": {"values": [{"id": 1}]}}},
                {"has_action_triggers": True},
            ),
            (
                {"steps": [], "conditions": {"events": {"values": [{"id": "event_1"}]}}},
                {"has_event_triggers": True},
            ),
            (
                {},
                {"step_count": 0, "has_url_condition": False, "has_action_triggers": False},
            ),
        ]
    )
    def test_get_analytics_metadata(self, content, expected_subset):
        tour = ProductTour.objects.create(
            team=self.team,
            name="Metadata test tour",
            content=content,
            created_by=self.user,
        )
        metadata = tour.get_analytics_metadata()

        for key, value in expected_subset.items():
            assert metadata[key] == value, f"Expected {key}={value}, got {metadata[key]}"

    def test_get_analytics_metadata_with_empty_content(self):
        tour = ProductTour.objects.create(
            team=self.team,
            name="Empty content tour",
            content={},
            created_by=self.user,
        )
        metadata = tour.get_analytics_metadata()
        assert metadata["step_count"] == 0
        assert metadata["has_url_condition"] is False


class TestProductTourLinkedSurveys(APIBaseTest):
    def test_linked_survey_launched_when_tour_launched(self):
        """When a tour with survey steps is launched, linked surveys should also be launched."""
        now = timezone.now()

        # Create a tour with a survey step
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Tour with survey",
                "content": {
                    "steps": [
                        {
                            "id": "step-1",
                            "selector": "#btn",
                            "survey": {
                                "type": "rating",
                                "questionText": "How helpful was this?",
                                "scale": 5,
                            },
                        }
                    ]
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        tour_id = response.json()["id"]
        linked_survey_id = response.json()["content"]["steps"][0]["linkedSurveyId"]

        # Survey should exist but not be launched yet
        survey = Survey.objects.get(id=linked_survey_id)
        assert survey.start_date is None

        # Launch the tour
        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"start_date": now.isoformat()},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # Survey should now be launched
        survey.refresh_from_db()
        assert survey.start_date is not None

    def test_linked_survey_ended_when_tour_ended(self):
        """When a tour is ended, linked surveys should also be ended."""
        now = timezone.now()

        # Create and launch a tour with a survey step
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Tour with survey",
                "start_date": now.isoformat(),
                "content": {
                    "steps": [
                        {
                            "id": "step-1",
                            "selector": "#btn",
                            "survey": {
                                "type": "open",
                                "questionText": "Any feedback?",
                            },
                        }
                    ]
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        tour_id = response.json()["id"]
        linked_survey_id = response.json()["content"]["steps"][0]["linkedSurveyId"]

        # Survey should be launched
        survey = Survey.objects.get(id=linked_survey_id)
        assert survey.start_date is not None
        assert survey.end_date is None

        # End the tour
        end_time = timezone.now()
        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"end_date": end_time.isoformat()},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        # Survey should now be ended
        survey.refresh_from_db()
        assert survey.end_date is not None

    def test_linked_survey_ended_when_tour_deleted(self):
        """When a tour is deleted (archived), linked surveys should be ended."""
        now = timezone.now()

        # Create and launch a tour with a survey step
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Tour to delete",
                "start_date": now.isoformat(),
                "content": {
                    "steps": [
                        {
                            "id": "step-1",
                            "selector": "#btn",
                            "survey": {
                                "type": "rating",
                                "questionText": "Rate this",
                                "scale": 5,
                            },
                        }
                    ]
                },
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        tour_id = response.json()["id"]
        linked_survey_id = response.json()["content"]["steps"][0]["linkedSurveyId"]

        # Survey should be launched
        survey = Survey.objects.get(id=linked_survey_id)
        assert survey.start_date is not None
        assert survey.end_date is None

        # Delete the tour
        response = self.client.delete(f"/api/projects/{self.team.id}/product_tours/{tour_id}/")
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Survey should now be ended
        survey.refresh_from_db()
        assert survey.end_date is not None


class TestProductTourInternalTargetingFlag(APIBaseTest):
    def test_flag_created_when_auto_launch_enabled_on_create(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Auto launch tour",
                "content": {"steps": []},
                "auto_launch": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        tour = ProductTour.objects.get(id=response.json()["id"])
        assert tour.internal_targeting_flag is not None
        assert not tour.internal_targeting_flag.active  # Draft state, no start_date

    def test_flag_activated_when_tour_launched(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Tour to launch",
                "content": {"steps": []},
                "auto_launch": True,
            },
            format="json",
        )
        tour_id = response.json()["id"]
        tour = ProductTour.objects.get(id=tour_id)
        assert tour.internal_targeting_flag is not None
        assert not tour.internal_targeting_flag.active

        # Launch the tour
        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"start_date": timezone.now().isoformat()},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        assert tour.internal_targeting_flag is not None
        flag = tour.internal_targeting_flag
        flag.refresh_from_db()
        assert flag.active

    def test_flag_deactivated_when_auto_launch_disabled(self):
        now = timezone.now()
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Running tour",
                "content": {"steps": []},
                "auto_launch": True,
                "start_date": now.isoformat(),
            },
            format="json",
        )
        tour_id = response.json()["id"]
        tour = ProductTour.objects.get(id=tour_id)
        assert tour.internal_targeting_flag is not None
        flag = tour.internal_targeting_flag
        assert flag.active

        # Disable auto_launch
        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"auto_launch": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        flag.refresh_from_db()
        assert not flag.active

    def test_flag_reactivated_when_auto_launch_reenabled(self):
        """Regression test: when auto_launch is toggled off then back on, flag should reactivate."""
        now = timezone.now()
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Toggle tour",
                "content": {"steps": []},
                "auto_launch": True,
                "start_date": now.isoformat(),
            },
            format="json",
        )
        tour_id = response.json()["id"]
        tour = ProductTour.objects.get(id=tour_id)
        assert tour.internal_targeting_flag is not None
        flag_id = tour.internal_targeting_flag.id
        assert FeatureFlag.objects.get(id=flag_id).active

        # Disable auto_launch
        self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"auto_launch": False},
            format="json",
        )
        assert not FeatureFlag.objects.get(id=flag_id).active

        # Re-enable auto_launch - flag should reactivate
        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"auto_launch": True},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        tour.refresh_from_db()
        # Should reuse the same flag, not create a new one
        assert tour.internal_targeting_flag is not None
        assert tour.internal_targeting_flag.id == flag_id
        assert FeatureFlag.objects.get(id=flag_id).active

    @parameterized.expand(
        [
            # (display_frequency, expected_exclusion_key_substrings)
            ("show_once", ["$product_tour_shown"]),
            ("until_interacted", ["$product_tour_completed", "$product_tour_dismissed"]),
            ("always", []),
            (None, ["$product_tour_completed", "$product_tour_dismissed"]),  # default behavior
        ]
    )
    def test_flag_exclusion_properties_on_create(self, display_frequency, expected_key_substrings):
        content: dict = {"steps": []}
        if display_frequency is not None:
            content["displayFrequency"] = display_frequency

        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Display frequency test",
                "content": content,
                "auto_launch": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        tour = ProductTour.objects.get(id=response.json()["id"])
        assert tour.internal_targeting_flag is not None

        properties = tour.internal_targeting_flag.filters.get("groups", [{}])[0].get("properties", [])
        property_keys = [p.get("key", "") for p in properties]

        if expected_key_substrings:
            for substring in expected_key_substrings:
                assert any(substring in key for key in property_keys), f"Expected {substring} in {property_keys}"
        else:
            assert len(properties) == 0, f"Expected no exclusion properties, got {properties}"

    @parameterized.expand(
        [
            # (initial_frequency, new_frequency, expected_exclusion_key_substrings)
            ("show_once", "until_interacted", ["$product_tour_completed", "$product_tour_dismissed"]),
            ("until_interacted", "show_once", ["$product_tour_shown"]),
            ("show_once", "always", []),
            ("always", "until_interacted", ["$product_tour_completed", "$product_tour_dismissed"]),
        ]
    )
    def test_flag_exclusion_properties_updated_on_display_frequency_change(
        self, initial_frequency, new_frequency, expected_key_substrings
    ):
        response = self.client.post(
            f"/api/projects/{self.team.id}/product_tours/",
            data={
                "name": "Frequency change test",
                "content": {"displayFrequency": initial_frequency, "steps": []},
                "auto_launch": True,
            },
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        tour_id = response.json()["id"]
        tour = ProductTour.objects.get(id=tour_id)

        # Update displayFrequency
        response = self.client.patch(
            f"/api/projects/{self.team.id}/product_tours/{tour_id}/",
            data={"content": {"displayFrequency": new_frequency, "steps": []}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        assert tour.internal_targeting_flag is not None
        tour.internal_targeting_flag.refresh_from_db()
        properties = tour.internal_targeting_flag.filters.get("groups", [{}])[0].get("properties", [])
        property_keys = [p.get("key", "") for p in properties]

        if expected_key_substrings:
            for substring in expected_key_substrings:
                assert any(substring in key for key in property_keys), f"Expected {substring} in {property_keys}"
        else:
            assert len(properties) == 0, f"Expected no exclusion properties, got {properties}"
