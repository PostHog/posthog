"""Keep the workflows scout running exactly where someone asked for suggestions.

The scout only reads live workflows whose owner turned on "Suggest improvements", so a project with
none gains nothing from its runs. The first live opted-in workflow switches the scout on for the
project, and losing the last one, by opting out, archiving or deleting it, removes it again.
"""

from django.db import connection, transaction
from django.db.models import Q

from posthog.models import Team, User

from products.signals.backend.facade.api import disable_scout_for_product, enable_scout_for_product
from products.workflows.backend.models import HogFlow, HogFlowOptimization

SUGGESTIONS_SCOUT = "signals-scout-workflows"
SOURCE_PRODUCT = "workflows"
PROPOSAL_WRITE_SCOPE = "hog_flow_proposal:write"
# Arbitrary, fixed namespace for the per-project advisory lock that serializes reconciliation.
_LOCK_NAMESPACE = 72_031


def sync_suggestions_scout(team: Team, *, acting_user: User | None, may_grant: bool) -> None:
    """Switch the scout on or off to match the project's live opted-in workflows.

    Switching it on grants `hog_flow_proposal:write` with `acting_user` as the person its runs act as,
    so it only happens when that person may grant the scope. Without one, a project that still needs
    the scout keeps whatever it has, and one that no longer needs it loses it.
    """
    # Scouts belong to the project's main environment, while workflows can live in any of its environments.
    project = team.parent_team or team
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [_LOCK_NAMESPACE, project.id])
        environments = Team.objects.filter(Q(id=project.id) | Q(parent_team_id=project.id)).values("id")
        wanted = (
            HogFlowOptimization.objects.unscoped()
            .filter(team_id__in=environments, enabled=True, hog_flow__status=HogFlow.State.ACTIVE)
            .exists()
        )
        if not wanted:
            disable_scout_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT, source_product=SOURCE_PRODUCT)
        elif acting_user is not None and may_grant:
            enable_scout_for_product(
                team=project,
                skill_name=SUGGESTIONS_SCOUT,
                source_product=SOURCE_PRODUCT,
                acting_user=acting_user,
                write_scopes=[PROPOSAL_WRITE_SCOPE],
            )
