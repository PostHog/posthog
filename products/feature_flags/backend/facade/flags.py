"""The read of an organization's flag_evaluations mode, the gates built on it, and whether a team has an active
flag. The module stays light so core code can import it without pulling the facade's heavier logic surface onto
its import path.
"""

from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from posthog.cloud_utils import is_cloud
from posthog.models.event.new_events_schema import use_new_events_schema
from posthog.models.instance_setting import get_instance_setting

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from posthog.models.team import Team


def has_active_flags(team: "Team") -> bool:
    """Whether the team has an active flag. Remote config sends this as `hasFeatureFlags`, and posthog-js requests
    flags on page load only when it is true. Without an active flag, a browser records no flag call until something
    else loads flags, for example `identify`."""
    # `team=`, not `team_id=`: the flag manager rewrites `team_id=` to the project's root team, which changes the
    # answer for an environment team and costs a join.
    return FeatureFlag.objects.filter(team=team, active=True).exists()


def get_organization_flag_evaluations_mode(organization_id: UUID) -> int:
    """The organization's FlagEvaluationsMode value. An organization with no config row reads EVENTS,
    which matches the COALESCE in Node ingestion's team query."""
    mode = (
        OrganizationFeatureFlagsConfig.objects.filter(organization_id=organization_id)
        .values_list("flag_evaluations_mode", flat=True)
        .first()
    )
    return FlagEvaluationsMode.EVENTS if mode is None else mode


def get_flag_evaluations_read_mode(organization_id: UUID) -> int:
    """The mode that picks the table for the flag-call readers that the READ_FLAG_EVALUATIONS comment lists.
    FLAG_EVALUATIONS_READS_FORCE_EVENTS makes it EVENTS for an organization on READ_FLAG_EVALUATIONS and leaves
    the stored mode unchanged. HogQL reads flag calls from flag_evaluations for a project on the native JSON events
    table whatever this returns, because that table holds no flag calls, so the switch does not move that project."""
    mode = get_organization_flag_evaluations_mode(organization_id)
    # The switch skips FLAG_EVALUATIONS_ONLY. For teams in the ingestion allowlist, events holds none of that
    # organization's flag calls, so the readers would show no calls instead of the flag_evaluations rows.
    if mode == FlagEvaluationsMode.READ_FLAG_EVALUATIONS and get_instance_setting(
        "FLAG_EVALUATIONS_READS_FORCE_EVENTS"
    ):
        return FlagEvaluationsMode.EVENTS
    return mode


def reads_flag_calls_from_flag_evaluations(team: "Team", modifiers: "HogQLQueryModifiers | None" = None) -> bool:
    """Whether a reader that picks its own table reads the team's flag calls from flag_evaluations. A team that reads
    the native JSON events table reads them there on every mode, because that table holds no flag calls. HogQL's
    swap follows the same rule in HogQLContext.reads_flag_calls_from_flag_evaluations."""
    if _reads_native_events_with_flag_evaluations(team, modifiers):
        return True
    return get_flag_evaluations_read_mode(team.organization_id) != FlagEvaluationsMode.EVENTS


def flag_calls_only_in_flag_evaluations(team: "Team") -> bool:
    """Whether a reader that picks its own table finds none of the team's new flag calls in the events table it
    reads: the organization is on FLAG_EVALUATIONS_ONLY, or the team reads the native JSON events table."""
    if _reads_native_events_with_flag_evaluations(team, None):
        return True
    return get_flag_evaluations_read_mode(team.organization_id) == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY


def _reads_native_events_with_flag_evaluations(team: "Team", modifiers: "HogQLQueryModifiers | None") -> bool:
    return use_new_events_schema(team.id, modifiers) and is_flag_evaluations_table_enabled(team)


def hides_flag_calls_from_query_builders(organization_id: UUID) -> bool:
    """Whether the organization's pickers leave out events marked hidden_in_query_builders, and the actions and
    cohorts APIs reject a new use of them. It reads the same mode as the team API's flag_evaluations_mode, which the
    frontend's hiddenEventNames reads, so the pickers and the APIs agree."""
    return get_flag_evaluations_read_mode(organization_id) != FlagEvaluationsMode.EVENTS


def is_flag_evaluations_table_enabled(team: "Team") -> bool:
    """Gate every surface that exposes `posthog.flag_evaluations` through here.

    Reads true on PostHog Cloud for every organization, whatever its flag_evaluations mode. A team on EVENTS
    can query the table, but its flag-call readers still read events. Local dev and end-to-end tests also read
    true. A self-hosted instance reads true only when the organization's mode reads the table.
    """
    # PostHog Cloud ingestion forks every team's flag calls into flag_evaluations, so an organization on
    # EVENTS still has rows to query and export.
    if is_cloud():
        return True
    # Local and E2E organizations start on EVENTS because FLAG_EVALUATIONS_NEW_ORG_MODE defaults to 0.
    # Returning True keeps the table queryable there without setting a mode first.
    if settings.DEBUG or settings.E2E_TESTING:
        return True
    # Self-hosted ingestion leaves the flag_evaluations fork off by default, so the table holds no rows there
    # until an operator turns the fork on. The Usage tab reads flag_evaluations for any mode above EVENTS, and
    # its query fails when the table is missing from the catalog.
    return get_organization_flag_evaluations_mode(team.organization_id) != FlagEvaluationsMode.EVENTS
