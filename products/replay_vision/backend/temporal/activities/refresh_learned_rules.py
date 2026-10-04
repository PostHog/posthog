from temporalio import activity

from posthog.models.team import Team

from products.replay_vision.backend.consent import is_ai_data_processing_approved
from products.replay_vision.backend.learned_rules import (
    LearnedRulesError,
    due_teams,
    refresh_team_learned_rules,
    stamp_run,
)
from products.replay_vision.backend.temporal.constants import LEARNED_RULES_MAX_TEAMS_PER_RUN
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.learned_rules_types import RefreshTeamLearnedRulesInputs


@activity.defn
@track_activity()
def list_due_learned_rules_teams_activity() -> list[RefreshTeamLearnedRulesInputs]:
    """Teams with settled new ratings, cut to the per-run cap."""
    return [RefreshTeamLearnedRulesInputs(team_id=team_id) for team_id in due_teams(LEARNED_RULES_MAX_TEAMS_PER_RUN)]


@activity.defn
@track_activity()
def refresh_team_learned_rules_activity(inputs: RefreshTeamLearnedRulesInputs) -> bool:
    """Distill one team's new ratings into its rulesets. False when nothing new was written: the team is gone,
    consent was withdrawn, or the ratings changed no rule."""
    team = Team.objects.filter(id=inputs.team_id).first()
    if team is None or not is_ai_data_processing_approved(inputs.team_id):
        return False
    try:
        return refresh_team_learned_rules(team)
    except LearnedRulesError:
        # Already logged with detail; the current rules stay.
        stamp_run(inputs.team_id)
        return False
    except Exception:
        stamp_run(inputs.team_id)
        raise
