"""
Tests for experiment presentation views.

These tests verify that view logic correctly handles both old and new
request formats and integrates with the facade API.
"""

from posthog.test.base import BaseTest

from rest_framework import status
from rest_framework.test import APIRequestFactory, force_authenticate

from posthog.models.feature_flag.feature_flag import FeatureFlag

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.presentation.views import ExperimentViewSet


class TestExperimentViewSet(BaseTest):
    """Unit tests for ExperimentViewSet."""

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def _create_view_with_context(self, request, team_id):
        """Helper to create a view with proper routing context."""
        view = ExperimentViewSet.as_view({"post": "create"})
        # Manually set parents_query_dict as the router would
        view.cls.parents_query_dict = {"team_id": team_id}
        return view(request)

    def test_create_experiment_with_new_format_feature_flag_filters(self):
        """Test creating experiment using new feature_flag_filters format."""
        data = {
            "name": "New Format Test",
            "feature_flag_key": "new-format-flag",
            "description": "Testing new format",
            "feature_flag_filters": {
                "key": "new-format-flag",
                "name": "New Format Flag",
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ],
            },
        }

        request = self.factory.post("/", data, format="json")
        force_authenticate(request, user=self.user)

        response = self._create_view_with_context(request, self.team.id)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "New Format Test"
        assert response.data["feature_flag_key"] == "new-format-flag"

        # Verify database objects were created
        experiment = Experiment.objects.get(id=response.data["id"])
        assert experiment.name == "New Format Test"

        flag = FeatureFlag.objects.get(key="new-format-flag", team=self.team)
        assert len(flag.filters["multivariate"]["variants"]) == 2

    def test_create_experiment_with_old_format_parameters(self):
        """Test creating experiment using old parameters format."""
        data = {
            "name": "Old Format Test",
            "feature_flag_key": "old-format-flag",
            "parameters": {
                "feature_flag_variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        }

        request = self.factory.post("/", data, format="json")
        force_authenticate(request, user=self.user)

        response = self._create_view_with_context(request, self.team.id)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Old Format Test"

        flag = FeatureFlag.objects.get(key="old-format-flag", team=self.team)
        assert len(flag.filters["multivariate"]["variants"]) == 2

    def test_create_experiment_rejects_both_formats(self):
        """Test that providing both formats returns 400 error."""
        data = {
            "name": "Both Formats Test",
            "feature_flag_key": "both-flag",
            "parameters": {
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ]
            },
            "feature_flag_filters": {
                "key": "both-flag",
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
            },
        }

        request = self.factory.post("/", data, format="json")
        force_authenticate(request, user=self.user)

        response = self._create_view_with_context(request, self.team.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "both" in str(response.data).lower()

        # Verify nothing was created
        assert not Experiment.objects.filter(name="Both Formats Test").exists()
        assert not FeatureFlag.objects.filter(key="both-flag").exists()

    def test_create_experiment_validates_variant_count(self):
        """Test that at least 2 variants are required."""
        data = {
            "name": "One Variant Test",
            "feature_flag_key": "one-variant-flag",
            "feature_flag_filters": {
                "key": "one-variant-flag",
                "variants": [
                    {"key": "control", "rollout_percentage": 100},
                ],
            },
        }

        request = self.factory.post("/", data, format="json")
        force_authenticate(request, user=self.user)

        response = self._create_view_with_context(request, self.team.id)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "variant" in str(response.data).lower()

    def test_create_experiment_minimal_required_fields(self):
        """Test creating experiment with only required fields."""
        data = {
            "name": "Minimal Test",
            "feature_flag_key": "minimal-flag",
        }

        request = self.factory.post("/", data, format="json")
        force_authenticate(request, user=self.user)

        response = self._create_view_with_context(request, self.team.id)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["name"] == "Minimal Test"
        assert response.data["feature_flag_key"] == "minimal-flag"
