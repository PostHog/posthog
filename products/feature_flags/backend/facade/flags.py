"""Feature-flag gates for this product, and the read of an organization's flag_evaluations mode.
The module stays light so core code can import it without pulling the facade's heavier logic
surface onto its import path.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from posthog.models.instance_setting import get_instance_setting
from posthog.ph_client import feature_enabled_or_false

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

if TYPE_CHECKING:
    from posthog.models.team import Team

FLAG_EVALUATIONS_HOGQL_TABLE_FEATURE_FLAG = "flag-evaluations-hogql-table"


def get_organization_flag_evaluations_mode(organization_id: UUID) -> int:
    """The organization's FlagEvaluationsMode value. An organization with no config row reads EVENTS,
    which matches the COALESCE in Node ingestion's team query."""
    mode = (
        OrganizationFeatureFlagsConfig.objects.filter(organization_id=organization_id)
        .values_list("flag_evaluations_mode", flat=True)
        .first()
    )
    return FlagEvaluationsMode.EVENTS if mode is None else mode


def get_usage_tab_flag_evaluations_mode(organization_id: UUID) -> int:
    """The mode that decides which table the flag Usage tab reads. FLAG_EVALUATIONS_USAGE_TAB_FORCE_EVENTS makes
    it EVENTS for an organization on READ_FLAG_EVALUATIONS and leaves the stored mode unchanged."""
    mode = get_organization_flag_evaluations_mode(organization_id)
    # The switch skips FLAG_EVALUATIONS_ONLY. Once ingestion supports that mode, events holds none of the
    # organization's flag calls, so the Usage tab would show empty days instead of the flag_evaluations rows.
    if mode == FlagEvaluationsMode.READ_FLAG_EVALUATIONS and get_instance_setting(
        "FLAG_EVALUATIONS_USAGE_TAB_FORCE_EVENTS"
    ):
        return FlagEvaluationsMode.EVENTS
    return mode


def is_flag_evaluations_table_enabled(team: "Team") -> bool:
    """Gate every surface that exposes `posthog.flag_evaluations` through here.

    Reads true when the flag_evaluations mode of the team's organization reads that table, or when the
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
    return flag_enabled or get_organization_flag_evaluations_mode(team.organization_id) != FlagEvaluationsMode.EVENTS
