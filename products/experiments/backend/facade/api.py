"""
Facade API for experiments product.

This module provides the public interface for creating and managing experiments
using framework-free DTOs, wrapping the existing ExperimentService.
"""

import logging

from rest_framework.exceptions import ValidationError

from posthog.schema import ExperimentQuery

from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.team import Team
from posthog.models.user import User

from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.models.experiment import Experiment as ExperimentModel

from .contracts import CreateExperimentInput, Experiment, ExperimentSignificanceResult, ExperimentVariantSignificance

logger = logging.getLogger(__name__)

# A generous but bounded cap: significance reads are best-effort evidence for a Foundry
# verdict proposal, not a UI page that must show every metric — one runaway experiment
# with dozens of metrics must not make a scout sweep pay for all of them.
MAX_METRICS_FOR_SIGNIFICANCE = 10


def create_experiment(*, team: Team, user: User, input_dto: CreateExperimentInput) -> Experiment:
    """
    Create a new experiment.

    Transactional safety is provided by ExperimentService.create_experiment.

    Args:
        team: Team creating the experiment
        user: User creating the experiment
        input_dto: Experiment creation input with all configuration

    Returns:
        Experiment DTO

    Raises:
        ValidationError: If validation fails in service layer
    """

    # Load holdout if ID provided
    from products.experiments.backend.models.experiment import ExperimentHoldout

    holdout = None
    if input_dto.holdout_id is not None:
        try:
            holdout = ExperimentHoldout.objects.get(id=input_dto.holdout_id, team_id=team.id)
        except ExperimentHoldout.DoesNotExist:
            raise ValidationError(f"Holdout with id {input_dto.holdout_id} does not exist for this team")

    # Convert tuple to list for ordering fields (DTO uses tuple for immutability)
    primary_metrics_ordered_uuids = list(input_dto.metrics_ordering) if input_dto.metrics_ordering else None
    secondary_metrics_ordered_uuids = (
        list(input_dto.secondary_metrics_ordering) if input_dto.secondary_metrics_ordering else None
    )

    # Call existing service (already @transaction.atomic)
    service = ExperimentService(team=team, user=user)
    experiment_model = service.create_experiment(
        name=input_dto.name,
        feature_flag_key=input_dto.feature_flag_key,
        description=input_dto.description,
        type=input_dto.type,
        parameters=input_dto.parameters,
        feature_flag_config=input_dto.feature_flag_config,
        running_time_calculation=input_dto.running_time_calculation,
        excluded_variants=input_dto.excluded_variants,
        metrics=input_dto.metrics,
        metrics_secondary=input_dto.metrics_secondary,
        secondary_metrics=input_dto.secondary_metrics,
        stats_config=input_dto.stats_config,
        exposure_criteria=input_dto.exposure_criteria,
        holdout=holdout,
        saved_metrics_ids=input_dto.saved_metrics_ids,
        start_date=input_dto.start_date,
        end_date=input_dto.end_date,
        primary_metrics_ordered_uuids=primary_metrics_ordered_uuids,
        secondary_metrics_ordered_uuids=secondary_metrics_ordered_uuids,
        create_in_folder=input_dto.create_in_folder,
        filters=input_dto.filters,
        scheduling_config=input_dto.scheduling_config,
        only_count_matured_users=input_dto.only_count_matured_users,
        archived=input_dto.archived,
        deleted=input_dto.deleted,
        conclusion=input_dto.conclusion,
        conclusion_comment=input_dto.conclusion_comment,
        repository=input_dto.repository,
        serializer_context=input_dto.serializer_context,
        allow_unknown_events=input_dto.allow_unknown_events,
    )

    # Convert model to DTO
    return _experiment_model_to_dto(experiment_model)


def get_experiment_significance(*, team: Team, experiment_id: int) -> ExperimentSignificanceResult | None:
    """Best-effort synchronous significance read off an experiment's primary metrics.

    Returns ``None`` when the experiment has no primary metrics configured — the common
    case for a freshly-funded Foundry bet (``metrics=[]`` by default, see
    ``products/foundry/backend/logic/__init__.py::fund_bet``), so this condition simply
    never fires until a human adds a metric — or when every metric query fails to
    parse/execute (logged, not raised: a caller sweeping many experiments must not crash
    on one bad one). Runs the same synchronous ``ExperimentQueryRunner`` engine the
    experiment results UI uses, one query per primary metric; no new metric computation.
    """
    try:
        experiment = ExperimentModel.objects.get(id=experiment_id, team_id=team.id)
    except ExperimentModel.DoesNotExist:
        return None
    metrics = experiment.metrics or []
    if not metrics:
        return None

    variants: list[ExperimentVariantSignificance] = []
    for metric_dict in metrics[:MAX_METRICS_FOR_SIGNIFICANCE]:
        try:
            query = ExperimentQuery(experiment_id=experiment_id, metric=metric_dict)
            response = ExperimentQueryRunner(query=query, team=team).run(
                execution_mode=ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
            )
        except Exception:
            logger.exception("experiments facade: significance query failed", extra={"experiment_id": experiment_id})
            continue
        for variant_result in getattr(response, "variant_results", None) or []:
            if variant_result.significant is not None:
                variants.append(
                    ExperimentVariantSignificance(key=variant_result.key, significant=variant_result.significant)
                )

    if not variants:
        return None
    return ExperimentSignificanceResult(
        metrics_evaluated=len(metrics),
        variants=variants,
        any_significant=any(v.significant for v in variants),
    )


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
