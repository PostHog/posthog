"""Feature-flag gates for this product, kept light so core code can import them without pulling
the facade's heavier logic surface onto its import path.
"""

from typing import TYPE_CHECKING

from django.conf import settings

from posthog.ph_client import feature_enabled_or_false

if TYPE_CHECKING:
    from posthog.models.team import Team

FLAG_EVALUATIONS_HOGQL_TABLE_FEATURE_FLAG = "flag-evaluations-hogql-table"


def is_flag_evaluations_table_enabled(team: "Team") -> bool:
    """Gate every surface that exposes `posthog.flag_evaluations` through here.

    Cloud-only for now: a self-hosted production instance reads false. Local dev and
    end-to-end tests are the exception and read true.
    """
    # The flag is evaluated against PostHog's own analytics project, which a local or end-to-end
    # environment has no membership in, so it would gate the table out of both.
    if settings.DEBUG or settings.E2E_TESTING:
        return True
    return feature_enabled_or_false(
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
