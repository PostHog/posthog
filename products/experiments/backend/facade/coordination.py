from uuid import UUID

from asgiref.sync import async_to_sync
from rest_framework.exceptions import PermissionDenied

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.models import Team, User

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.experiments.backend.experiment_service import ExperimentService
from products.experiments.backend.experiment_summary_data_service import ExperimentSummaryDataService
from products.experiments.backend.health.loader import load_experiment_health_inputs
from products.experiments.backend.health.registry import EXPERIMENT_HEALTH_CHECKS, evaluate
from products.experiments.backend.metric_resolution import get_effective_experiment_metrics
from products.experiments.backend.models.experiment import Experiment

from .contracts import ExperimentHealthReaderAccess


def _evidence(*, team: Team, user: User, experiment_id: int) -> dict:
    experiment = (
        Experiment.objects.filter(team=team, id=experiment_id, deleted=False).select_related("feature_flag").first()
    )
    access = UserAccessControl(user=user, team=team)
    if experiment is None or not access.check_access_level_for_object(experiment, "viewer"):
        raise PermissionDenied("This experiment is unavailable to the bet owner.")
    can_query = True
    # Health reads these native caches too, so refresh them before evaluating exposure and metric health.
    data = (
        async_to_sync(ExperimentSummaryDataService(team, user).fetch_experiment_data)(
            experiment.id, cache_age_seconds=300
        )
        if experiment.start_date and can_query
        else None
    )
    restrictions = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.id)
    inputs = load_experiment_health_inputs(
        team_id=team.id,
        experiment_id=experiment.id,
        user=user,
        reader_access=ExperimentHealthReaderAccess(
            can_read_flag_history=access.check_access_level_for_object(experiment.feature_flag, "viewer")
            and access.check_access_level_for_resource("activity_log", "viewer"),
            can_query_events=can_query,
            denied_event_properties=split_restricted_property_names(restrictions).event,
        ),
    )
    health = evaluate(inputs.context, EXPERIMENT_HEALTH_CHECKS)
    effective = get_effective_experiment_metrics(experiment)
    result = {
        "id": experiment.id,
        "name": experiment.name,
        "start_date": experiment.start_date.isoformat() if experiment.start_date else None,
        "end_date": experiment.end_date.isoformat() if experiment.end_date else None,
        "flag_active": experiment.feature_flag.active,
        "conclusion": experiment.conclusion,
        "configuration": {
            "feature_flag_key": experiment.feature_flag.key,
            "metrics": [
                {key: value for key, value in item.definition.items() if key != "fingerprint"}
                for item in effective
                if item.role == "primary"
            ],
            "secondary_metrics": [
                {key: value for key, value in item.definition.items() if key != "fingerprint"}
                for item in effective
                if item.role == "secondary"
            ],
            "only_count_matured_users": experiment.only_count_matured_users,
            "exposure_criteria": experiment.exposure_criteria,
            "filters": experiment.feature_flag.filters,
        },
        "findings": [
            {"code": str(finding.code), "detail": finding.detail, "severity": str(finding.severity)}
            for finding in health.findings
        ],
        "unchecked": [str(check.key) for check in health.checks if check.status == "not_checked"],
        "unchecked_reasons": {str(check.key): check.reason for check in health.checks if check.status == "not_checked"},
        "exposure_status": str(inputs.exposures.status),
        "exposure_error": inputs.exposures.error,
        "exposure_findings": [finding.model_dump(mode="json") for finding in inputs.exposures.findings],
        "results": None,
        "pending": True,
    }
    if data is not None:
        result.update(
            results={**data.context.model_dump(mode="json"), "metric_sample_counts": data.metric_sample_counts},
            pending=data.pending_calculation or data.omitted_metric_count > 0,
            computed_at=data.last_refresh.isoformat() if data.last_refresh else None,
        )
    return result


def evidence(*, team: Team, user: User, experiment_id: int) -> dict:
    with tags_context(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.id, user_id=user.id):
        return _evidence(team=team, user=user, experiment_id=experiment_id)


def conclude(*, team: Team, user: User, experiment_id: int, conclusion: str, comment: str, repository: str) -> None:
    experiment = Experiment.objects.filter(team=team, id=experiment_id, deleted=False).first()
    if experiment is None or not UserAccessControl(user=user, team=team).check_access_level_for_object(
        experiment, "editor"
    ):
        raise PermissionDenied("This experiment is unavailable to the bet owner.")
    if experiment.end_date:
        return
    ExperimentService(team, user).end_experiment(
        experiment,
        conclusion=conclusion,
        conclusion_comment=comment,
        open_cleanup_pr=True,
        repository=repository,
    )


def ship(
    *, team: Team, user: User, experiment_id: int, variant: str, conclusion: str, comment: str, repository: str
) -> None:
    experiment = Experiment.objects.filter(team=team, id=experiment_id, deleted=False).first()
    if experiment is None or not UserAccessControl(user=user, team=team).check_access_level_for_object(
        experiment, "editor"
    ):
        raise PermissionDenied("This experiment is unavailable to the bet owner.")
    ExperimentService(team, user).ship_variant(
        experiment,
        variant,
        release_to_everyone=True,
        conclusion=conclusion,
        conclusion_comment=comment,
        open_cleanup_pr=not experiment.end_date,
        repository=repository,
        request=None,
    )


def cleanup_task_id(*, team: Team, experiment_id: int) -> UUID | None:
    return (
        Experiment.objects.filter(team=team, id=experiment_id, deleted=False)
        .values_list("flag_cleanup_task_id", flat=True)
        .first()
    )
