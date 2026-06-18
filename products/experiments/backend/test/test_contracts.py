"""
Tests for experiment contracts (DTOs).

These tests verify that our frozen dataclasses are immutable,
hashable, and have the correct structure.

NOTE: Tests for FeatureFlagVariant and CreateFeatureFlagInput were removed
in PR #4 to keep the facade simple. The facade only supports the old
parameters format for now.
"""

from datetime import UTC, datetime

import pytest
from freezegun import freeze_time

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

    @freeze_time("2026-03-21T12:00:00Z")
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

    @freeze_time("2026-03-21T12:00:00Z")
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
            parameters={"feature_flag_variants": [{"key": "control", "rollout_percentage": 50}]},
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
        """Test creating experiment with parameters format."""
        input_dto = CreateExperimentInput(
            name="My Experiment",
            feature_flag_key="my-flag",
            parameters={
                "feature_flag_variants": [
                    {"key": "control", "rollout_percentage": 50},
                    {"key": "test", "rollout_percentage": 50},
                ]
            },
        )

        assert input_dto.parameters is not None
        assert "feature_flag_variants" in input_dto.parameters


@freeze_time("2026-03-21T12:00:00Z")
class TestFeatureFlag:
    def test_feature_flag_output(self):
        """Test feature flag output DTO."""
        flag = FeatureFlag(
            id=123,
            key="my-flag",
            name="My Flag",
            active=True,
            created_at=datetime.now(UTC),
        )

        assert flag.id == 123
        assert flag.key == "my-flag"
        assert flag.name == "My Flag"
        assert flag.active is True


@freeze_time("2026-03-21T12:00:00Z")
class TestExperiment:
    def test_experiment_output_minimal(self):
        """Test experiment output DTO with minimal fields."""
        exp = Experiment(
            id=456,
            name="My Experiment",
            feature_flag_id=123,
            feature_flag_key="my-flag",
            is_draft=True,
            created_at=datetime.now(UTC),
        )

        assert exp.id == 456
        assert exp.name == "My Experiment"
        assert exp.feature_flag_id == 123
        assert exp.is_draft is True

    def test_experiment_output_full(self):
        """Test experiment output with all fields."""
        now = datetime.now(UTC)
        exp = Experiment(
            id=456,
            name="My Experiment",
            description="Test description",
            feature_flag_id=123,
            feature_flag_key="my-flag",
            is_draft=False,
            start_date=now,
            end_date=None,
            created_at=now,
            updated_at=now,
        )

        assert exp.description == "Test description"
        assert exp.is_draft is False
        assert exp.start_date == now
        assert exp.updated_at == now
