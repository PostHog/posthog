"""Keep the workflows scout running exactly where someone asked for suggestions.

The scout only reads live workflows whose owner turned on "Suggest improvements", so a project with
none gains nothing from its runs. The first live opted-in workflow switches the scout on for the
project, and losing the last one, by opting out, archiving or deleting it, removes it again.
"""

from datetime import timedelta
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from posthog.api.app_metrics2 import fetch_app_metric_totals
from posthog.models import Team, User

from products.signals.backend.facade.api import (
    ScoutEnableRefusal,
    disable_scout_for_product,
    enable_scout_for_product,
    scout_emits_for_product,
    scout_enable_refusal_for_product,
    scout_status_for_product,
)
from products.workflows.backend.facade.contracts import SuggestionsSample
from products.workflows.backend.metrics import (
    HOG_FLOW_VERSION_APP_SOURCE,
    MIN_EVIDENCE_SAMPLE,
    TARGET_SEND_METRIC,
    TARGET_UNTRACKED_METRIC,
)
from products.workflows.backend.models import HogFlow, HogFlowOptimization, HogFlowRevision

SUGGESTIONS_SCOUT = "signals-scout-workflows"
SOURCE_PRODUCT = "workflows"
PROPOSAL_WRITE_SCOPE = "hog_flow_proposal:write"
# The scout's sample floor: tracked sends per email step, read over this window, from a version live this long.
SAMPLE_WINDOW = timedelta(days=7)
SAMPLE_MIN_VERSION_AGE = timedelta(hours=48)
# Arbitrary, fixed namespace for the per-project advisory lock that serializes reconciliation.
_LOCK_NAMESPACE = 72_031


def sync_suggestions_scout(team: Team, *, acting_user: User | None, may_grant: bool) -> None:
    """Switch the scout on or off to match the project's live opted-in workflows.

    Switching it on grants `hog_flow_proposal:write` and makes `acting_user` the person its runs act as,
    so it happens only with an `acting_user` and `may_grant` set. Switching it off needs neither.
    When the project still needs the scout but nobody here may grant it, the scout config stays as it is.
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


def suggestions_scout_refusal(team: Team, *, acting_user: User, may_grant: bool) -> ScoutEnableRefusal | str | None:
    """Why turning suggestions on here would leave the project with no scout, or None when it would not.

    A project that already has the scout needs nothing new, so nothing is refused there.
    """
    project = team.parent_team or team
    if scout_status_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT) is not None:
        return None
    if not may_grant:
        return "key_cannot_grant"
    return scout_enable_refusal_for_product(
        team=project, skill_name=SUGGESTIONS_SCOUT, acting_user=acting_user, write_scopes=[PROPOSAL_WRITE_SCOPE]
    )


def suggestions_scout_status(team: Team) -> str:
    """`running`, `dry_run`, `paused_by_user`, `paused_by_system` or `not_running` for the project's suggestions scout."""
    project = team.parent_team or team
    status = scout_status_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT)
    if status is None:
        return "not_running"
    if status in ("paused_by_user", "paused_by_system"):
        return status
    # A dry run holds no write scopes, so it can never file a suggestion.
    if scout_emits_for_product(team_id=project.id, skill_name=SUGGESTIONS_SCOUT) is False:
        return "dry_run"
    return "running"


def suggestions_sample(*, team_id: int, hog_flow_id: UUID) -> SuggestionsSample | None:
    """Whether any email step of the live version clears the scout's sample floor, or None without an email step."""
    flow = (
        HogFlow.objects.filter(team_id=team_id, pk=hog_flow_id).only("id", "version", "actions", "created_at").first()
    )
    if flow is None:
        return None
    step_ids = [
        str(action["id"])
        for action in flow.actions or []
        if isinstance(action, dict) and action.get("type") == "function_email" and action.get("id")
    ]
    if not step_ids:
        return None
    revision = (
        HogFlowRevision.objects.for_team(team_id)
        .filter(hog_flow=flow, version=flow.version)
        .values_list("created_at", flat=True)
    )
    # A flow with no revision for its version predates revision tracking, so it has been live at least since creation.
    live_since = revision.first() or flow.created_at
    now = timezone.now()
    tracked_sends = 0
    for step_id in step_ids:
        totals = fetch_app_metric_totals(
            team_id=team_id,
            app_source=HOG_FLOW_VERSION_APP_SOURCE,
            app_source_id=f"{flow.id}/{flow.version}",
            breakdown_by="name",
            after=now - SAMPLE_WINDOW,
            instance_id=step_id,
            name=[TARGET_SEND_METRIC, TARGET_UNTRACKED_METRIC],
        ).totals
        sent = int(totals.get(TARGET_SEND_METRIC, 0)) - int(totals.get(TARGET_UNTRACKED_METRIC, 0))
        tracked_sends = max(tracked_sends, sent)
        if tracked_sends >= MIN_EVIDENCE_SAMPLE:
            break
    return SuggestionsSample(
        reached=tracked_sends >= MIN_EVIDENCE_SAMPLE and now - live_since >= SAMPLE_MIN_VERSION_AGE,
        tracked_sends=tracked_sends,
        required_sends=MIN_EVIDENCE_SAMPLE,
        version_live_since=live_since,
    )
