"""
Facade API for experiments product.

This module provides the public interface for creating and managing experiments
using framework-free DTOs, wrapping the existing ExperimentService.
"""

from posthog.models.team import Team
from posthog.models.user import User

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.models.experiment import Experiment as ExperimentModel

from .contracts import CreateExperimentInput, Experiment


def create_experiment(*, team: Team, user: User, input_dto: CreateExperimentInput) -> Experiment:
    """
    Create a new experiment.

    Supports both old format (parameters.feature_flag_variants)
    and new format (feature_flag_filters).

    Transactional safety is provided by ExperimentService.create_experiment.

    Args:
        team: Team creating the experiment
        user: User creating the experiment
        input_dto: Experiment creation input

    Returns:
        Experiment DTO

    Raises:
        ValueError: If both old and new formats are provided
    """
    # Validate that both formats are not provided
    has_old_format = input_dto.parameters is not None and "feature_flag_variants" in input_dto.parameters
    has_new_format = input_dto.feature_flag_filters is not None

    if has_old_format and has_new_format:
        raise ValueError("Cannot provide both 'parameters.feature_flag_variants' and 'feature_flag_filters'")

    # Prepare parameters for service call
    # Start with any provided parameters (e.g., minimum_detectable_effect)
    parameters_dict = dict(input_dto.parameters) if input_dto.parameters else {}

    if has_new_format:
        # Convert CreateFeatureFlagInput to parameters dict format
        flag_filters = input_dto.feature_flag_filters
        assert flag_filters is not None  # Type guard: has_new_format guarantees this

        parameters_dict["feature_flag_variants"] = [
            {
                "key": variant.key,
                "name": variant.name,
                "rollout_percentage": variant.split_percent,
            }
            for variant in flag_filters.variants
        ]

        # Add optional fields
        if flag_filters.rollout_percentage is not None:
            parameters_dict["rollout_percentage"] = flag_filters.rollout_percentage
        if flag_filters.aggregation_group_type_index is not None:
            parameters_dict["aggregation_group_type_index"] = flag_filters.aggregation_group_type_index
        if flag_filters.ensure_experience_continuity is not None:
            parameters_dict["ensure_experience_continuity"] = flag_filters.ensure_experience_continuity

    # Pass None if dict is empty to maintain service contract
    parameters = parameters_dict or None

    # Call existing service (already @transaction.atomic)
    service = ExperimentService(team=team, user=user)
    experiment_model = service.create_experiment(
        name=input_dto.name,
        feature_flag_key=input_dto.feature_flag_key,
        description=input_dto.description,
        parameters=parameters,
    )

    # Convert model to DTO
    return _experiment_model_to_dto(experiment_model)


def _experiment_model_to_dto(experiment: ExperimentModel) -> Experiment:
    """Convert Django model to DTO."""
    return Experiment(
        id=experiment.id,
        name=experiment.name,
        description=experiment.description or None,
        feature_flag_id=experiment.feature_flag_id,
        feature_flag_key=experiment.feature_flag.key,
        is_draft=experiment.start_date is None,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        created_at=experiment.created_at,
        updated_at=experiment.updated_at,
    )
