"""
Tests for experiment facade API.

These tests verify that the facade correctly wraps the existing
ExperimentService and converts between Django models and DTOs.
"""

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.feature_flag.feature_flag import FeatureFlag as FeatureFlagModel

from products.experiments.backend.facade.api import create_experiment
from products.experiments.backend.facade.contracts import (
    CreateExperimentInput,
    CreateFeatureFlagInput,
    Experiment,
    FeatureFlagVariant,
)
from products.experiments.backend.models.experiment import Experiment as ExperimentModel


class TestCreateExperiment(BaseTest):
    def test_create_experiment_with_new_format(self):
        """Test creating experiment using new feature_flag_filters format."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag",
            description="Test description",
            feature_flag_filters=CreateFeatureFlagInput(
                key="test-flag",
                name="Test Flag",
                variants=(
                    FeatureFlagVariant(key="control", name="Control", split_percent=50),
                    FeatureFlagVariant(key="test", name="Test", split_percent=50),
                ),
            ),
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        # Verify output DTO structure
        assert isinstance(result, Experiment)
        assert result.name == "Test Experiment"
        assert result.feature_flag_key == "test-flag"
        assert result.is_draft is True

        # Verify database objects were created
        experiment = ExperimentModel.objects.get(id=result.id)
        assert experiment.name == "Test Experiment"
        assert experiment.feature_flag.key == "test-flag"

        # Verify feature flag created
        flag = FeatureFlagModel.objects.get(id=result.feature_flag_id)
        # Note: Currently the service generates its own flag name
        # Full feature_flag_filters support (including name) will come in a later phase
        assert flag.name == "Feature Flag for Experiment Test Experiment"
        assert len(flag.filters["multivariate"]["variants"]) == 2

    def test_create_experiment_with_old_format(self):
        """Test creating experiment using old parameters format."""
        input_dto = CreateExperimentInput(
            name="Test Experiment",
            feature_flag_key="test-flag",
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "name": "Control", "rollout_percentage": 50},
                    {"key": "test", "name": "Test", "rollout_percentage": 50},
                ]
            },
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        # Verify output DTO structure
        assert isinstance(result, Experiment)
        assert result.name == "Test Experiment"
        assert result.feature_flag_key == "test-flag"
        assert result.is_draft is True

        # Verify database objects were created
        experiment = ExperimentModel.objects.get(id=result.id)
        assert experiment.name == "Test Experiment"
        assert experiment.feature_flag.key == "test-flag"

        # Verify feature flag created
        flag = FeatureFlagModel.objects.get(id=result.feature_flag_id)
        assert flag.name == "Feature Flag for Experiment Test Experiment"
        assert len(flag.filters["multivariate"]["variants"]) == 2

    def test_create_experiment_with_existing_flag(self):
        """Test creating experiment with existing feature flag."""
        # Create flag first
        existing_flag = FeatureFlagModel.objects.create(
            team=self.team,
            created_by=self.user,
            key="existing-flag",
            filters={
                "groups": [{"properties": [], "rollout_percentage": 100}],
                "multivariate": {
                    "variants": [
                        {"key": "control", "rollout_percentage": 50},
                        {"key": "test", "rollout_percentage": 50},
                    ]
                },
            },
        )

        input_dto = CreateExperimentInput(
            name="Existing Flag Experiment",
            feature_flag_key="existing-flag",
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        assert result.feature_flag_id == existing_flag.id
        assert result.feature_flag_key == "existing-flag"

    def test_create_experiment_rejects_both_formats(self):
        """Test that providing both old and new formats raises error."""
        input_dto = CreateExperimentInput(
            name="Both Formats",
            feature_flag_key="both-flag",
            parameters={"feature_flag_variants": [{"key": "control", "rollout_percentage": 100}]},
            feature_flag_filters=CreateFeatureFlagInput(
                key="both-flag",
                variants=(FeatureFlagVariant(key="control", split_percent=100),),
            ),
        )

        with pytest.raises(ValueError, match="Cannot provide both"):
            create_experiment(team=self.team, user=self.user, input_dto=input_dto)

    def test_create_experiment_is_transactional(self):
        """Test that experiment creation is transactional."""
        # Patch Experiment.objects.create to fail after flag creation
        with patch("products.experiments.backend.models.experiment.Experiment.objects.create") as mock_create:
            mock_create.side_effect = Exception("Experiment creation failed")

            input_dto = CreateExperimentInput(
                name="Transactional Test",
                feature_flag_key="transaction-flag",
                feature_flag_filters=CreateFeatureFlagInput(
                    key="transaction-flag",
                    variants=(FeatureFlagVariant(key="control", split_percent=100),),
                ),
            )

            with pytest.raises(Exception, match="Experiment creation failed"):
                create_experiment(team=self.team, user=self.user, input_dto=input_dto)

            # Verify rollback - flag should not exist despite being created first
            assert not FeatureFlagModel.objects.filter(key="transaction-flag").exists()
            assert not ExperimentModel.objects.filter(name="Transactional Test").exists()

    def test_output_dto_immutability(self):
        """Test that returned DTO is immutable."""
        input_dto = CreateExperimentInput(
            name="Immutable Test",
            feature_flag_key="immutable-flag",
            parameters={"feature_flag_variants": [{"key": "control", "rollout_percentage": 100}]},
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)

        with pytest.raises(AttributeError):
            result.name = "Modified"  # type: ignore

    def test_output_dto_hashability(self):
        """Test that returned DTO is hashable."""
        input_dto = CreateExperimentInput(
            name="Hashable Test",
            feature_flag_key="hashable-flag",
            parameters={"feature_flag_variants": [{"key": "control", "rollout_percentage": 100}]},
        )

        result = create_experiment(team=self.team, user=self.user, input_dto=input_dto)
        assert hash(result) is not None
