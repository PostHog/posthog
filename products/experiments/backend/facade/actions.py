"""Experiments reads for the actions product: the experiments that reference an action."""

import json
from collections.abc import Sequence

from django.db import connection

from products.actions.backend.facade.enums import ACTION_REFERENCE_JSONPATH, ACTIONS_ARRAY_JSONPATH
from products.experiments.backend.experiment_creator import to_experiment_creator
from products.experiments.backend.facade.contracts import ExperimentActionReference
from products.experiments.backend.models.experiment import Experiment

__all__ = [
    "count_experiments_referencing_actions",
    "experiments_referencing_action",
]

_EXPERIMENT_JSON_FIELDS = (
    "metrics",
    "metrics_secondary",
    "filters",
    "parameters",
    "exposure_criteria",
    "stats_config",
    "scheduling_config",
    "variants",
)


def experiments_referencing_action(
    team_id: int, action_id: int, *, limit: int
) -> tuple[ExperimentActionReference, ...]:
    """Up to `limit` experiments of the team that are not deleted and that reference the action in their metrics,
    filters or configuration."""
    vars_json = json.dumps({"id": action_id, "id_str": str(action_id)})

    exp_conditions = []
    for field in _EXPERIMENT_JSON_FIELDS:
        exp_conditions.append(f"jsonb_path_exists({field}, '{ACTION_REFERENCE_JSONPATH}', %s::jsonb)")
        exp_conditions.append(f"jsonb_path_exists({field}, '{ACTIONS_ARRAY_JSONPATH}', %s::jsonb)")

    # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
    experiments = (
        Experiment.objects.filter(team_id=team_id)
        .exclude(deleted=True)
        .select_related("created_by")
        .extra(where=[" OR ".join(exp_conditions)], params=[vars_json] * len(exp_conditions))
    )
    return tuple(
        ExperimentActionReference(
            id=experiment.id,
            name=experiment.name,
            created_at=experiment.created_at,
            created_by=to_experiment_creator(experiment.created_by) if experiment.created_by else None,
        )
        for experiment in experiments[:limit]
    )


def count_experiments_referencing_actions(team_id: int, action_ids: Sequence[int]) -> dict[int, int]:
    """For each action, how many experiments of the team that are not deleted reference it. An action without a
    reference is absent from the result."""
    if not action_ids:
        return {}

    exp_conditions = []
    for field in _EXPERIMENT_JSON_FIELDS:
        exp_conditions.append(
            f"jsonb_path_exists({field}, '{ACTION_REFERENCE_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))"
        )
        exp_conditions.append(
            f"jsonb_path_exists({field}, '{ACTIONS_ARRAY_JSONPATH}', jsonb_build_object('id', aid, 'id_str', aid::text))"
        )
    exp_table = Experiment._meta.db_table
    exp_where = " OR ".join(exp_conditions)

    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (parameterized via %s)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT aid, count(*) FROM unnest(%s::int[]) AS aid
            CROSS JOIN LATERAL (
                SELECT 1 FROM {exp_table}
                WHERE team_id = %s AND NOT COALESCE(deleted, false)
                AND ({exp_where})
            ) AS matched
            GROUP BY aid
            """,
            [list(action_ids), team_id],
        )
        return dict(cursor.fetchall())
