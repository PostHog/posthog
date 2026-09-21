"""
Tests for experiment contracts (DTOs).

These tests verify that our frozen dataclasses are immutable,
hashable, and have the correct structure.

The parameters field carries experiment-own metadata (variant_notes,
prompt_metadata, custom_exposure_filter) only; flag config goes through
the experiment's feature_flag object, not here.
"""

from datetime import UTC, datetime

import pytest
import time_machine

from products.experiments.backend.facade.contracts import CreateExperimentInput, Experiment, FeatureFlag


class TestContractImmutability:
    """Test that all contracts are immutable (frozen dataclasses)."""

    @pytest.mark.parametrize(
        ("instance", "field_name", "new_value"),
        [
            pytest.param(
                CreateExperimentInput(name="Test", feature_flag_key="test-flag"),
                "name",
                "modified",
                id="CreateExperimentInput",
            ),
        ],
    )
    def test_input_contracts_are_immutable(self, instance, field_name, new_value):
        """Test that input contract instances cannot be modified after creation."""
        with pytest.raises(AttributeError):
            setattr(instance, field_name, new_value)

    @time_machine.travel("2026-03-21T12:00:00Z", tick=False)
    @pytest.mark.parametrize(
        ("instance", "field_name", "new_value"),
        [
            pytest.param(
                FeatureFlag(
                    id=123,
                    key="test",
                    active=False,
                    created_at=datetime.now(UTC),
                ),
                "active",
                True,
                id="FeatureFlag",
            ),
            pytest.param(
                Experiment(
                    id=456,
                    name="Test",
                    feature_flag_id=123,
                    feature_flag_key="test",
                    is_draft=True,
                    created_at=datetime.now(UTC),
                ),
                "name",
                "modified",
                id="Experiment",
            ),
        ],
    )
    def test_output_contracts_are_immutable(self, instance, field_name, new_value):
        """Test that output contract instances cannot be modified after creation."""
        with pytest.raises(AttributeError):
            setattr(instance, field_name, new_value)


class TestContractHashability:
    """Test that contracts are hashable (required for Turbo caching)."""

    @time_machine.travel("2026-03-21T12:00:00Z", tick=False)
    @pytest.mark.parametrize(
        "instance",
        [
            pytest.param(
                FeatureFlag(
                    id=123,
                    key="test",
                    active=False,
                    created_at=datetime.now(UTC),
                ),
                id="FeatureFlag",
            ),
            pytest.param(
                Experiment(
                    id=456,
                    name="Test",
                    feature_flag_id=123,
                    feature_flag_key="test",
                    is_draft=True,
                    created_at=datetime.now(UTC),
                ),
                id="Experiment",
            ),
        ],
    )
    def test_output_contracts_are_hashable(self, instance):
        """Test that output contracts can be hashed (raises TypeError if not hashable)."""
        hash(instance)

    def test_experiment_input_with_parameters_is_not_hashable(self):
        """Test that CreateExperimentInput with parameters dict is not hashable.

        The parameters field contains mutable types (dict/list) so the DTO
        is not hashable when those fields are set.
        """
        input_dto = CreateExperimentInput(
            name="Test",
            feature_flag_key="test-flag",
            parameters={"variant_notes": {"control": "baseline"}},
        )

        with pytest.raises(TypeError, match="unhashable type"):
            hash(input_dto)


class TestCreateExperimentInput:
    def test_create_experiment_input_minimal(self):
        """Test creating experiment input with minimal fields."""
        input_dto = CreateExperimentInput(
            name="My Experiment",
            feature_flag_key="my-flag",
        )

        assert input_dto.name == "My Experiment"
        assert input_dto.feature_flag_key == "my-flag"
        assert input_dto.description == ""
        assert input_dto.parameters is None

    def test_create_experiment_input_with_parameters_format(self):
        """parameters carries experiment-own keys (variant_notes), not flag config."""
        input_dto = CreateExperimentInput(
            name="My Experiment",
            feature_flag_key="my-flag",
            parameters={"variant_notes": {"control": "baseline", "test": "new"}},
        )

        assert input_dto.parameters is not None
        assert "variant_notes" in input_dto.parameters
