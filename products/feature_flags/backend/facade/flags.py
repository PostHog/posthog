"""Feature-flag gates for this product, kept light so core code can import them without pulling
the facade's heavier logic surface onto its import path.
"""

from typing import TYPE_CHECKING

from django.conf import settings

from posthog.ph_client import feature_enabled_or_false

from products.feature_flags.backend.models.team_feature_flags_config import FlagEvaluationsMode, TeamFeatureFlagsConfig

if TYPE_CHECKING:
    from posthog.models.team import Team

FLAG_EVALUATIONS_HOGQL_TABLE_FEATURE_FLAG = "flag-evaluations-hogql-table"


def get_team_flag_evaluations_mode(team_id: int) -> int:
    """The team's FlagEvaluationsMode value. A team with no config row reads EVENTS, which matches
    the COALESCE in Node ingestion's team query."""
    mode = (
        TeamFeatureFlagsConfig.objects.filter(team_id=team_id).values_list("flag_evaluations_mode", flat=True).first()
    )
    return FlagEvaluationsMode.EVENTS if mode is None else mode


def is_flag_evaluations_table_enabled(team: "Team") -> bool:
    """Gate every surface that exposes `posthog.flag_evaluations` through here.

    Reads true when the team's flag_evaluations mode reads that table, or when the
    flag-evaluations-hogql-table flag is on for the team's organization. A self-hosted production
    instance has neither by default and reads false. Local dev and end-to-end tests are the
    exception and read true.
    """
    # The flag is evaluated against PostHog's own analytics project, which a local or end-to-end
    # environment has no membership in. Evaluating it there would hide the table from both, so
    # return True to keep it visible in dev and E2E.
    if settings.DEBUG or settings.E2E_TESTING:
        return True
    flag_enabled = feature_enabled_or_false(
        FLAG_EVALUATIONS_HOGQL_TABLE_FEATURE_FLAG,
        str(team.organization_id),
        groups={"organization": str(team.organization_id)},
        group_properties={"organization": {"id": str(team.organization_id)}},
        # The HogQL database is built on the query hot path, and a local-evaluation miss otherwise
        # blocks it on a synchronous request to /flags. Failing closed hides the table instead.
        # This constrains how the flag may be configured: target organizations by the id sent
        # above, because a condition on any property not sent here cannot evaluate locally and so
        # reads false for everyone.
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )
    # The flag evaluates in memory, so it goes first and a flagged organization skips the query.
    # The Usage tab reads flag_evaluations for any mode above EVENTS, and its query fails when the
    # table is missing from the catalog, so the mode alone has to be enough.
    return flag_enabled or get_team_flag_evaluations_mode(team.id) != FlagEvaluationsMode.EVENTS
