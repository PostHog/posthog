"""
Tests for experiment presentation serializers.

These tests verify that DRF serializers correctly handle both old and new
request formats and convert them to facade DTOs.
"""

from posthog.test.base import BaseTest

from products.experiments.backend.facade.contracts import CreateExperimentInput, CreateFeatureFlagInput
from products.experiments.backend.presentation.serializers import ExperimentCreateSerializer


class TestExperimentCreateSerializer(BaseTest):
    def test_validate_new_format_with_feature_flag_filters(self):
        """Test validation of new feature_flag_filters format."""
        data = {
            "name": "Test Experiment",
            "feature_flag_key": "test-flag",
            "description": "Test description",
            "feature_flag_filters": {
                "key": "test-flag",
                "name": "Test Flag",
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ],
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert serializer.is_valid(), serializer.errors

        # Verify it produces the correct DTO
        dto = serializer.to_facade_dto()
        assert isinstance(dto, CreateExperimentInput)
        assert dto.name == "Test Experiment"
        assert dto.feature_flag_key == "test-flag"
        assert dto.feature_flag_filters is not None
        assert isinstance(dto.feature_flag_filters, CreateFeatureFlagInput)
        assert len(dto.feature_flag_filters.variants) == 2

    def test_validate_old_format_with_parameters(self):
        """Test validation of old parameters format."""
        data = {
            "name": "Old Format Experiment",
            "feature_flag_key": "old-flag",
            "parameters": {
                "feature_flag_variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert serializer.is_valid(), serializer.errors

        dto = serializer.to_facade_dto()
        assert isinstance(dto, CreateExperimentInput)
        assert dto.parameters is not None
        assert "feature_flag_variants" in dto.parameters
        assert dto.feature_flag_filters is None

    def test_validate_rejects_both_formats(self):
        """Test that providing both formats raises validation error."""
        data = {
            "name": "Both Formats",
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

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors
        assert "both" in str(serializer.errors).lower()

    def test_validate_minimal_data(self):
        """Test validation with minimal required fields."""
        data = {
            "name": "Minimal Experiment",
            "feature_flag_key": "minimal-flag",
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert serializer.is_valid(), serializer.errors

        dto = serializer.to_facade_dto()
        assert dto.name == "Minimal Experiment"
        assert dto.description == ""
        assert dto.parameters is None
        assert dto.feature_flag_filters is None

    def test_validate_feature_flag_filters_nested_structure(self):
        """Test nested validation of feature_flag_filters."""
        data = {
            "name": "Nested Test",
            "feature_flag_key": "nested-flag",
            "feature_flag_filters": {
                "key": "nested-flag",
                "name": "Nested Flag",
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
                "rollout_percentage": 100,
                "aggregation_group_type_index": 0,
                "ensure_experience_continuity": True,
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert serializer.is_valid(), serializer.errors

        dto = serializer.to_facade_dto()
        assert dto.feature_flag_filters is not None
        assert dto.feature_flag_filters.rollout_percentage == 100
        assert dto.feature_flag_filters.aggregation_group_type_index == 0
        assert dto.feature_flag_filters.ensure_experience_continuity is True

    def test_validate_feature_flag_filters_requires_variants(self):
        """Test that feature_flag_filters requires variants."""
        data = {
            "name": "No Variants",
            "feature_flag_key": "no-variants-flag",
            "feature_flag_filters": {
                "key": "no-variants-flag",
                "name": "No Variants Flag",
                # Missing variants
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "feature_flag_filters" in serializer.errors

    def test_validate_variant_rollout_percentages(self):
        """Test validation of variant rollout percentages."""
        data = {
            "name": "Invalid Percentages",
            "feature_flag_key": "invalid-flag",
            "feature_flag_filters": {
                "key": "invalid-flag",
                "variants": [
                    {"key": "control", "rollout_percentage": -10},  # Invalid
                ],
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()

    def test_to_facade_dto_preserves_all_fields(self):
        """Test that to_facade_dto preserves all input fields."""
        data = {
            "name": "Complete Test",
            "feature_flag_key": "complete-flag",
            "description": "Complete description",
            "feature_flag_filters": {
                "key": "complete-flag",
                "name": "Complete Flag",
                "variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 33},
                    {"key": "test_a", "name": "Test A", "rollout_percentage": 33},
                    {"key": "test_b", "name": "Test B", "rollout_percentage": 34},
                ],
                "rollout_percentage": 80,
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert serializer.is_valid(), serializer.errors

        dto = serializer.to_facade_dto()
        assert dto.name == "Complete Test"
        assert dto.description == "Complete description"
        assert dto.feature_flag_filters is not None
        assert len(dto.feature_flag_filters.variants) == 3
        assert dto.feature_flag_filters.variants[0].name == "Control"
        assert dto.feature_flag_filters.variants[1].key == "test_a"
        assert dto.feature_flag_filters.rollout_percentage == 80
