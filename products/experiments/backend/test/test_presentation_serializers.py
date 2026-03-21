"""
Tests for experiment presentation serializers.

These tests verify that DRF serializers correctly handle both old and new
request formats and convert them to facade DTOs.
"""

import pytest
from posthog.test.base import BaseTest

from products.experiments.backend.facade.contracts import CreateExperimentInput, CreateFeatureFlagInput
from products.experiments.backend.presentation.serializers import ExperimentCreateSerializer


@pytest.mark.django_db
class TestExperimentCreateSerializer:
    @pytest.fixture(autouse=True)
    def setup(self, team, user):
        self.team = team
        self.user = user

    @pytest.mark.parametrize(
        "data,expected_valid,expected_attrs",
        [
            # New format with feature_flag_filters
            (
                {
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
                },
                True,
                {
                    "name": "Test Experiment",
                    "feature_flag_key": "test-flag",
                    "has_feature_flag_filters": True,
                    "variant_count": 2,
                },
            ),
            # Old format with parameters
            (
                {
                    "name": "Old Format Experiment",
                    "feature_flag_key": "old-flag",
                    "parameters": {
                        "feature_flag_variants": [
                            {"key": "control", "name": "Control", "rollout_percentage": 50},
                            {"key": "test", "name": "Test", "rollout_percentage": 50},
                        ]
                    },
                },
                True,
                {"name": "Old Format Experiment", "has_parameters": True, "has_feature_flag_filters": False},
            ),
            # Minimal data
            (
                {"name": "Minimal Experiment", "feature_flag_key": "minimal-flag"},
                True,
                {"name": "Minimal Experiment", "description": "", "parameters": None, "feature_flag_filters": None},
            ),
            # Nested structure with all optional fields
            (
                {
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
                },
                True,
                {"rollout_percentage": 100, "aggregation_group_type_index": 0, "ensure_experience_continuity": True},
            ),
            # Complete test with all fields
            (
                {
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
                },
                True,
                {
                    "name": "Complete Test",
                    "description": "Complete description",
                    "variant_count": 3,
                    "variant_0_name": "Control",
                    "variant_1_key": "test_a",
                    "rollout_percentage": 80,
                },
            ),
        ],
        ids=[
            "new_format_feature_flag_filters",
            "old_format_parameters",
            "minimal_data",
            "nested_structure_all_fields",
            "complete_test_all_fields",
        ],
    )
    def test_valid_serializer_cases(self, data, expected_valid, expected_attrs):
        """Test valid serialization cases with various input formats."""
        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert serializer.is_valid() == expected_valid, serializer.errors

        if expected_valid:
            dto = serializer.to_facade_dto()
            assert isinstance(dto, CreateExperimentInput)

            # Check expected attributes
            if "name" in expected_attrs:
                assert dto.name == expected_attrs["name"]
            if "feature_flag_key" in expected_attrs:
                assert dto.feature_flag_key == expected_attrs["feature_flag_key"]
            if "description" in expected_attrs:
                assert dto.description == expected_attrs["description"]
            if "parameters" in expected_attrs:
                assert dto.parameters == expected_attrs["parameters"]
            if "feature_flag_filters" in expected_attrs:
                assert (dto.feature_flag_filters is None) == (expected_attrs["feature_flag_filters"] is None)
            if "has_feature_flag_filters" in expected_attrs:
                assert (dto.feature_flag_filters is not None) == expected_attrs["has_feature_flag_filters"]
                if expected_attrs["has_feature_flag_filters"]:
                    assert isinstance(dto.feature_flag_filters, CreateFeatureFlagInput)
            if "has_parameters" in expected_attrs:
                assert (dto.parameters is not None) == expected_attrs["has_parameters"]
                if expected_attrs["has_parameters"] and dto.parameters is not None:
                    assert "feature_flag_variants" in dto.parameters
            if "variant_count" in expected_attrs and dto.feature_flag_filters:
                assert len(dto.feature_flag_filters.variants) == expected_attrs["variant_count"]
            if "variant_0_name" in expected_attrs and dto.feature_flag_filters:
                assert dto.feature_flag_filters.variants[0].name == expected_attrs["variant_0_name"]
            if "variant_1_key" in expected_attrs and dto.feature_flag_filters:
                assert dto.feature_flag_filters.variants[1].key == expected_attrs["variant_1_key"]
            if "rollout_percentage" in expected_attrs and dto.feature_flag_filters:
                assert dto.feature_flag_filters.rollout_percentage == expected_attrs["rollout_percentage"]
            if "aggregation_group_type_index" in expected_attrs and dto.feature_flag_filters:
                assert (
                    dto.feature_flag_filters.aggregation_group_type_index
                    == expected_attrs["aggregation_group_type_index"]
                )
            if "ensure_experience_continuity" in expected_attrs and dto.feature_flag_filters:
                assert (
                    dto.feature_flag_filters.ensure_experience_continuity
                    == expected_attrs["ensure_experience_continuity"]
                )

    @pytest.mark.parametrize(
        "data,expected_error_field",
        [
            # Both formats provided
            (
                {
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
                },
                "non_field_errors",
            ),
            # Missing variants
            (
                {
                    "name": "No Variants",
                    "feature_flag_key": "no-variants-flag",
                    "feature_flag_filters": {"key": "no-variants-flag", "name": "No Variants Flag"},
                },
                "feature_flag_filters",
            ),
            # Invalid rollout percentage
            (
                {
                    "name": "Invalid Percentages",
                    "feature_flag_key": "invalid-flag",
                    "feature_flag_filters": {
                        "key": "invalid-flag",
                        "variants": [{"key": "control", "rollout_percentage": -10}],
                    },
                },
                None,  # Any error is acceptable
            ),
        ],
        ids=["both_formats", "missing_variants", "invalid_percentage"],
    )
    def test_invalid_serializer_cases(self, data, expected_error_field):
        """Test invalid serialization cases."""
        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        if expected_error_field:
            assert expected_error_field in serializer.errors

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

    def test_validate_control_variant_required(self):
        """Test that control variant is required in new format."""
        data = {
            "name": "No Control Test",
            "feature_flag_key": "no-control-flag",
            "feature_flag_filters": {
                "key": "no-control-flag",
                "variants": [
                    {"key": "test_a", "rollout_percentage": 50},
                    {"key": "test_b", "rollout_percentage": 50},
                ],
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "feature_flag_filters" in serializer.errors
        assert "control" in str(serializer.errors).lower()

    def test_validate_control_variant_required_old_format(self):
        """Test that control variant is required in old format."""
        data = {
            "name": "No Control Old Format",
            "feature_flag_key": "no-control-old-flag",
            "parameters": {
                "feature_flag_variants": [
                    {"key": "test_a", "rollout_percentage": 50},
                    {"key": "test_b", "rollout_percentage": 50},
                ]
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "parameters" in serializer.errors
        assert "control" in str(serializer.errors).lower()

    def test_validate_duplicate_variant_keys(self):
        """Test that duplicate variant keys are rejected."""
        data = {
            "name": "Duplicate Keys Test",
            "feature_flag_key": "duplicate-keys-flag",
            "feature_flag_filters": {
                "key": "duplicate-keys-flag",
                "variants": [
                    {"key": "control", "rollout_percentage": 33},
                    {"key": "test", "rollout_percentage": 33},
                    {"key": "test", "rollout_percentage": 34},  # Duplicate
                ],
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "feature_flag_filters" in serializer.errors
        assert "unique" in str(serializer.errors).lower()

    def test_validate_duplicate_variant_keys_old_format(self):
        """Test that duplicate variant keys are rejected in old format."""
        data = {
            "name": "Duplicate Keys Old",
            "feature_flag_key": "duplicate-keys-old-flag",
            "parameters": {
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 33},
                    {"key": "test", "rollout_percentage": 33},
                    {"key": "test", "rollout_percentage": 34},  # Duplicate
                ]
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "parameters" in serializer.errors
        assert "unique" in str(serializer.errors).lower()

    def test_validate_too_many_variants(self):
        """Test that more than 20 variants are rejected."""
        variants = [{"key": "control", "rollout_percentage": 5}]
        variants.extend([{"key": f"test_{i}", "rollout_percentage": 5} for i in range(20)])

        data = {
            "name": "Too Many Variants",
            "feature_flag_key": "too-many-variants-flag",
            "feature_flag_filters": {
                "key": "too-many-variants-flag",
                "variants": variants,
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "feature_flag_filters" in serializer.errors
        assert "21" in str(serializer.errors)

    def test_validate_too_many_variants_old_format(self):
        """Test that more than 20 variants are rejected in old format."""
        variants = [{"key": "control", "rollout_percentage": 5}]
        variants.extend([{"key": f"test_{i}", "rollout_percentage": 5} for i in range(20)])

        data = {
            "name": "Too Many Variants Old",
            "feature_flag_key": "too-many-variants-old-flag",
            "parameters": {"feature_flag_variants": variants},
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "parameters" in serializer.errors
        assert "21" in str(serializer.errors)

    def test_validate_feature_flag_key_already_exists(self):
        """Test that existing feature flag keys are rejected."""
        from posthog.models.feature_flag.feature_flag import FeatureFlag

        # Create an existing feature flag
        FeatureFlag.objects.create(team=self.team, key="existing-flag", created_by=self.user)

        data = {
            "name": "Duplicate Flag Key",
            "feature_flag_key": "existing-flag",
            "feature_flag_filters": {
                "key": "existing-flag",
                "variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ],
            },
        }

        serializer = ExperimentCreateSerializer(data=data, context={"get_team": lambda: self.team})
        assert not serializer.is_valid()
        assert "feature_flag_key" in serializer.errors
        assert "already exists" in str(serializer.errors).lower()
