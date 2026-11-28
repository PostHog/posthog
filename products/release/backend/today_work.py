"""Loads the facts of releases for their work threads, through the facades of the products that own them."""

from uuid import UUID

from django.utils import timezone

from posthog.models import Team, User
from posthog.paging import PageRequest

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.early_access_features.backend.facade.api import EarlyAccessListAccess, early_access_features_for_flags
from products.experiments.backend.facade.api import live_experiments_by_flag
from products.experiments.backend.facade.contracts import ExperimentBasic, ExperimentListFilters, ListAccess
from products.experiments.backend.facade.experiments import list_experiments
from products.feature_flags.backend.facade.release_candidates import release_flag_states
from products.today.backend.facade.contracts import WorkContext, WorkThread

from .facade import api, contracts
from .logic.work_thread import ReleaseWorkFacts, is_in_flight, release_work_thread
from .presentation.link_lookups import ReleaseLinkVisibility

IN_FLIGHT_THREAD_LIMIT = 20
IN_FLIGHT_SCAN_LIMIT = 50
EXPERIMENT_PAGE_SIZE = 100


def _experiment_access(access_control: UserAccessControl, viewer_id: int) -> ListAccess | None:
    access = access_control.list_access_filter("experiment")
    if access is None:
        return None
    return ListAccess(
        viewer_id=viewer_id,
        only_allowed=access.only_allowed,
        allowed_ids=access.allowed_ids,
        blocked_ids=access.blocked_ids,
    )


def _early_access_access(access_control: UserAccessControl, viewer_id: int) -> EarlyAccessListAccess | None:
    access = access_control.list_access_filter("early_access_feature", include_all_if_admin=True)
    if access is None:
        return None
    return EarlyAccessListAccess(
        viewer_id=viewer_id,
        only_allowed=access.only_allowed,
        allowed_ids=access.allowed_ids,
        blocked_ids=access.blocked_ids,
    )


def _visible_experiments(team: Team, flag_ids: list[int], access: ListAccess | None) -> list[ExperimentBasic]:
    experiments: list[ExperimentBasic] = []
    for archived in ("false", "true"):
        filters = ExperimentListFilters(
            feature_flag_ids=",".join(str(flag_id) for flag_id in flag_ids), archived=archived
        )
        offset = 0
        while True:
            page = list_experiments(
                team=team, filters=filters, access=access, page=PageRequest(limit=EXPERIMENT_PAGE_SIZE, offset=offset)
            )
            experiments.extend(page.results)
            offset += len(page.results)
            if not page.results or offset >= page.count:
                break
    return experiments


def _work_experiment(experiment: ExperimentBasic) -> contracts.WorkExperiment:
    return contracts.WorkExperiment(
        id=experiment.id,
        name=experiment.name,
        feature_flag_key=experiment.feature_flag_key,
        status=experiment.status,
        start_date=experiment.start_date,
        end_date=experiment.end_date,
        archived=experiment.archived,
        conclusion=experiment.conclusion,
        conclusion_comment=experiment.conclusion_comment,
    )


def load_flag_details(
    *, team: Team, user: User, access_control: UserAccessControl, flag_ids: list[int]
) -> contracts.ReleaseFlagDetails:
    flags = release_flag_states(team_id=team.id, flag_ids=flag_ids, access_control=access_control)
    shown_ids = [flag.id for flag in flags]
    if not shown_ids:
        return contracts.ReleaseFlagDetails(
            flags=(), experiments=(), early_access_features=(), incomplete_flag_ids=frozenset()
        )
    experiments = _visible_experiments(team, shown_ids, _experiment_access(access_control, user.id))
    loaded_experiment_ids = {experiment.id for experiment in experiments}
    early_access = early_access_features_for_flags(
        team_id=team.id, flag_ids=shown_ids, access=_early_access_access(access_control, user.id)
    )
    hidden_experiment_flag_ids = {
        flag_id
        for flag_id, linked in live_experiments_by_flag(shown_ids).items()
        if any(experiment.id not in loaded_experiment_ids for experiment in linked)
    }
    return contracts.ReleaseFlagDetails(
        flags=tuple(
            contracts.WorkFlag(
                id=flag.id,
                key=flag.key,
                active=flag.active,
                archived=flag.archived,
                created_at=flag.created_at,
                is_v1_config=flag.is_v1_config,
                aggregation_group_type_index=flag.aggregation_group_type_index,
                conditions=tuple(
                    contracts.WorkFlagCondition(
                        property_count=condition.property_count,
                        rollout_percentage=condition.rollout_percentage,
                        variant=condition.variant,
                        aggregation_group_type_index=condition.aggregation_group_type_index,
                    )
                    for condition in flag.conditions
                ),
                variants=tuple(
                    contracts.WorkFlagVariant(key=variant.key, rollout_percentage=variant.rollout_percentage)
                    for variant in flag.variants
                ),
                early_exit=flag.early_exit,
                feature_enrollment=flag.feature_enrollment,
                holdout_exclusion_percentage=flag.holdout_exclusion_percentage,
            )
            for flag in flags
        ),
        experiments=tuple(_work_experiment(experiment) for experiment in experiments),
        early_access_features=tuple(
            contracts.WorkEarlyAccessFeature(
                id=feature.id,
                name=feature.name,
                stage=feature.stage,
                created_at=feature.created_at,
                feature_flag_id=feature.feature_flag_id,
            )
            for feature in early_access.features
        ),
        incomplete_flag_ids=frozenset(hidden_experiment_flag_ids | early_access.hidden_flag_ids),
    )


def _releases_enabled(team: Team, user: User) -> bool:
    return api.releases_enabled(
        team_id=team.id,
        team_uuid=team.uuid,
        organization_id=team.organization_id,
        distinct_id=str(user.distinct_id),
        email=None if user.anonymize_data else user.email,
    )


def _release_id(ref: str) -> UUID | None:
    try:
        return UUID(ref)
    except ValueError:
        return None


def find_release_work_threads(context: WorkContext) -> list[WorkThread]:
    """With a release id in `context.ref`, that release's thread. Without one, the threads of releases in flight.

    The viewer sees what the release API would show them: flags, surveys, insights and broadcasts that their access
    controls or their key's scopes hide stay out.
    """
    team, user = context.team, context.user
    if not _releases_enabled(team, user):
        return []
    access_control = UserAccessControl(user=user, team=team)
    lookups = ReleaseLinkVisibility(team=team, access_control=access_control, held_scopes=context.scopes).lookups()
    if context.ref is not None:
        release_id = _release_id(context.ref)
        if release_id is None:
            return []
        try:
            releases = [api.get(team.id, release_id, lookups)]
        except api.ReleaseNotFoundError:
            return []
    else:
        releases = api.list_recently_updated(team.id, IN_FLIGHT_SCAN_LIMIT, lookups)
    can_edit = access_control.check_access_level_for_resource("feature_flag", "editor")
    now = timezone.now().astimezone(team.timezone_info)
    flag_ids = sorted({flag_id for release in releases for flag_id in release.feature_flag_ids})
    details = load_flag_details(team=team, user=user, access_control=access_control, flag_ids=flag_ids)
    threads: list[WorkThread] = []
    for release in releases:
        facts = ReleaseWorkFacts(release=release, details=details, now=now, can_edit=can_edit)
        if context.ref is None and not is_in_flight(facts):
            continue
        threads.append(release_work_thread(facts))
        if len(threads) == IN_FLIGHT_THREAD_LIMIT:
            break
    return threads
