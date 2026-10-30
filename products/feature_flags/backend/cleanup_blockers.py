from collections.abc import Collection

from posthog.models.team import Team

from products.early_access_features.backend.models import EarlyAccessFeature
from products.experiments.backend.facade import api as experiments_api
from products.feature_flags.backend.flag_version_sync import direct_flag_dependency_ids, flags_with_flag_dependencies
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.session_recording_links import replay_gated_flags_for_projects
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey


def excluded_flag_ids(candidates: list[FeatureFlag]) -> set[int]:
    """Flag ids that known blockers reference, not limited to the candidate ids.

    Every lookup is scoped by team or project rather than by candidate flag id, so each
    one binds a handful of parameters per batch and can return ids for flags outside it.

    Every lookup is one set-wise query over the batch; the count stays fixed as the
    candidate volume grows. These exclusions remove known blockers only. They do not prove
    the remaining flags are free of repository references or product intent.

    The bulk-delete guard in ``products/feature_flags/backend/api/feature_flag.py`` blocks
    the same references and must stay in step with this list. Where the two differ it is on
    purpose, and this list is the stricter one: the guard blocks only running experiments
    where this excludes every non-deleted one, the guard's ``find_dependent_flags_batch``
    counts only active dependent flags where this also lets disabled dependents block, and
    the guard matches a replay gate only within the flag's own project where this matches a
    stored id across every project scanned.

    A survey's user-created ``linked_flag`` is deliberately not excluded, unlike the
    survey flags PostHog generates itself. It is user-managed, bulk delete permits it, and
    the remediation tells the investigator to check surveys. A reported flag is evidence
    to investigate, not a verdict that removal is safe.
    """
    team_ids = {flag.team_id for flag in candidates}
    # Product tours, replay links, and flag dependencies are scoped by project, not by team:
    # another team in the same project can reference a flag this batch's teams own. A product
    # tour stays on the environment that created it, while a flag moves to the project root.
    # Surveys stay on team scope: Survey and FeatureFlag both inherit RootTeamMixin, so both
    # rows always sit on the project root team and their team ids line up.
    team_projects = dict(Team.objects.filter(id__in=team_ids).values_list("id", "project_id"))
    project_ids = set(team_projects.values())

    excluded: set[int] = set()
    excluded |= Survey.get_internal_flag_ids(team_ids=team_ids)
    excluded |= set(
        # nosemgrep: environment-model-scoped-by-project -- feature flags live on the project root team and a tour on any environment of the project can own an internal targeting flag
        ProductTour.all_objects.filter(
            team__project_id__in=project_ids, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
    )
    excluded |= experiments_api.experiment_flag_ids(team_ids, include_deleted=False)
    excluded |= set(
        EarlyAccessFeature.objects.filter(team_id__in=team_ids, feature_flag_id__isnull=False).values_list(
            "feature_flag_id", flat=True
        )
    )
    excluded |= _depended_on_flag_ids(project_ids)
    # A trigger group counts here as much as the linked-flag column: both gate recording, so a
    # flag either one names must not be reported as a cleanup candidate.
    replay_gates = replay_gated_flags_for_projects(project_ids)
    # A stored id is matched against every project scanned, because flag ids are globally unique.
    # Only the stored key reaches an SDK, so a team holding another project's flag id gates no
    # recording on that flag. The candidate is withheld anyway, because a hard delete leaves that
    # reference unrepairable. `repair_replay_linked_flag_keys` reports such a row as
    # `FLAG_IN_OTHER_PROJECT` and has no key it can safely adopt.
    excluded |= {flag_id for gates in replay_gates.values() for flag_id in gates.flag_ids}
    # A stored key is matched only within its own project, because a key names one flag only
    # there, and pooling keys would let a key stored in one project protect a same-keyed flag in
    # another.
    excluded |= {
        flag.id
        for flag in candidates
        if (project_id := team_projects.get(flag.team_id)) is not None
        and (gates := replay_gates.get(project_id)) is not None
        and flag.key in gates.flag_keys
    }
    return excluded


def _depended_on_flag_ids(project_ids: Collection[int]) -> set[int]:
    """Ids of flags that at least one non-deleted flag has a flag-type condition on.

    Matches local-evaluation payload semantics (all non-deleted flags, active or not):
    a disabled dependent still ships in the payload and can be re-enabled, so it must
    keep protecting its dependency from cleanup.
    """
    dependents = flags_with_flag_dependencies(project_ids)
    depended_on: set[int] = set()
    for dependent in dependents:
        depended_on |= direct_flag_dependency_ids(dependent)
    return depended_on
