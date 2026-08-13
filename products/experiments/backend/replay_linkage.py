"""Person-scoped exposure linkage for replay surfaces.

Resolves an experiment's exposed population to one row per distinct id, carrying the person's
first exposure time, so recordings queries can show sessions of exposed persons. Built on the
same ExposureQueryBuilder the analysis queries use, which keeps exposure criteria, activation
events, and multiple-variant handling consistent with what the experiment's results count.

Linking by person and first exposure time, instead of requiring an exposure event inside the
session, is what keeps server-fired exposure events linkable: they carry no usable
``$session_id`` (none at all, or a context-generated one that matches no recording), but the
person's other distinct ids do appear on recordings. Expanding the exposed persons through
``raw_person_distinct_ids`` also covers cross-device sessions and anonymous pre-identify ids.
"""

from datetime import UTC, datetime

from django.contrib.auth.models import AnonymousUser

from rest_framework.exceptions import ValidationError

from posthog.schema import IntervalType

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.rbac.user_access_control import UserAccessControl, UserAccessControlError
from posthog.synthetic_user import SyntheticUser

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window
from products.experiments.backend.hogql_queries.cuped_config import CupedQueryConfig
from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureQueryBuilder
from products.experiments.backend.hogql_queries.experiment_query_builder import get_exposure_config_params_for_builder
from products.experiments.backend.hogql_queries.experiment_query_context import ExperimentQueryContext
from products.experiments.backend.hogql_queries.exposure_query_logic import get_entity_key
from products.experiments.backend.models.experiment import Experiment


def validate_experiment_exposure_access(
    team: Team, user: User | AnonymousUser | SyntheticUser | None, experiment_id: int
) -> bool:
    """Refuse the ``experiment_exposure`` filter for viewers denied the experiment it names.

    The filter reveals experiment data through replay surfaces (which recordings belong to
    exposed persons, and to which variant), but recordings endpoints only enforce replay-level
    access — so the experiment's own object-level check must run here, matching what the
    experiment surfaces enforce for the same information.

    Refuses userless callers outright: a background job's output can reach viewers this check
    never evaluated (the playlist counting task caches match counts that any playlist viewer
    can read), so running the filter without a viewer can leak experiment data to viewers the
    experiment denies. A background consumer must supply the principal on whose behalf it
    runs, or not use the filter. Service-token principals and anonymous shared-link viewers
    are non-User principals outside object-level RBAC and pass; they are gated by API scope
    plus project membership, and by the sharing publish gate, respectively. An unknown
    experiment also passes, because there is no object to protect and
    :func:`exposed_distinct_ids_select` reports it as a ValidationError.

    Returns True, or raises UserAccessControlError (the query-runner access contract).
    """
    if user is None:
        raise UserAccessControlError("experiment", "viewer", resource_id=str(experiment_id))
    if not isinstance(user, User):
        return True
    experiment = Experiment.objects.filter(id=experiment_id, team=team, deleted=False).first()
    if experiment is None:
        return True
    if not UserAccessControl(user=user, team=team).check_access_level_for_object(experiment, required_level="viewer"):
        raise UserAccessControlError("experiment", "viewer", resource_id=str(experiment_id))
    return True


def exposed_distinct_ids_select(team: Team, *, experiment_id: int, variant: str | None) -> ast.SelectQuery:
    """One row per exposed distinct id: (distinct_id, first_exposure_time).

    Raises ValidationError for experiments the linkage can't answer for: unknown or draft
    experiments, and group-aggregated ones, whose exposed entities are groups rather than
    persons and so never match a recording's distinct id.
    """
    try:
        experiment = Experiment.objects.get(id=experiment_id, team=team, deleted=False)
    except Experiment.DoesNotExist:
        raise ValidationError(f"Experiment {experiment_id} doesn't exist in this environment.")

    flag = getattr(experiment, "feature_flag", None)
    if flag is None:
        raise ValidationError("This experiment has no feature flag, so exposures can't be resolved.")
    if experiment.start_date is None:
        raise ValidationError("This experiment hasn't launched, so it has no exposed sessions yet.")
    if (flag.filters or {}).get("aggregation_group_type_index") is not None:
        raise ValidationError(
            "This experiment aggregates by group, so its exposures can't be matched to persons' recordings."
        )

    excluded_variants = set(experiment.excluded_variants or [])
    variant_keys = [
        variant_definition["key"]
        for variant_definition in flag.variants or []
        if variant_definition.get("key") and variant_definition["key"] not in excluded_variants
    ]
    if not variant_keys:
        raise ValidationError("This experiment's feature flag defines no variants.")
    if variant is not None:
        if variant not in variant_keys:
            raise ValidationError(f"'{variant}' is not a variant of this experiment.")
        requested_variants = [variant]
    else:
        requested_variants = variant_keys

    exposure_params = get_exposure_config_params_for_builder(experiment.exposure_criteria, team, experiment.start_date)
    date_range_query = QueryDateRange(
        date_range=experiment_window(experiment, team, as_of=experiment.end_date or datetime.now(UTC)),
        team=team,
        interval=IntervalType.DAY,
        now=datetime.now(UTC),
    )
    context = ExperimentQueryContext(
        team=team,
        feature_flag_key=flag.key_without_tombstone(),
        exposure_config=exposure_params.exposure_config,
        filter_test_accounts=exposure_params.filter_test_accounts,
        multiple_variant_handling=exposure_params.multiple_variant_handling,
        # The full variant list, not the requested one: variant attribution and multiple-variant
        # detection must see every variant, or a person exposed to two variants would pass as
        # cleanly exposed to the requested one. Narrowing happens in the WHERE below instead.
        variants=tuple(variant_keys),
        date_range_query=date_range_query,
        entity_key=get_entity_key(None),
        breakdowns=(),
        only_count_matured_users=False,
        cuped_config=CupedQueryConfig(),
        activation_config=exposure_params.activation_config,
    )
    exposure_select = ExposureQueryBuilder(context=context).select_query()

    # The WHERE on variant also drops entities attributed MULTIPLE_VARIANT_KEY under "exclude"
    # handling, matching who the analysis counts. Both join sides are pre-grouped, so each
    # distinct id carries exactly one exposure row and min() merely satisfies the GROUP BY.
    query = parse_select(
        """
        SELECT
            pdi.distinct_id AS distinct_id,
            min(exposures.first_exposure_time) AS first_exposure_time
        FROM (
            SELECT
                distinct_id,
                argMax(person_id, version) AS person_id,
                argMax(is_deleted, version) AS is_deleted
            FROM raw_person_distinct_ids
            WHERE team_id = {team_id}
            GROUP BY distinct_id
            HAVING is_deleted = 0
        ) AS pdi
        INNER JOIN ({exposure_select}) AS exposures ON exposures.entity_id = pdi.person_id
        WHERE exposures.variant IN {requested_variants}
        GROUP BY pdi.distinct_id
        """,
        placeholders={
            "team_id": ast.Constant(value=team.pk),
            "exposure_select": exposure_select,
            "requested_variants": ast.Constant(value=requested_variants),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query
