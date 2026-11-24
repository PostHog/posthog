"""The read of an organization's flag_evaluations mode, the gates built on it, and whether a team has an active
flag. The module stays light so core code can import it without pulling the facade's heavier logic surface onto
its import path.
"""

from collections.abc import Collection
from typing import TYPE_CHECKING
from uuid import UUID

from django.conf import settings

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.models.event.new_events_schema import (
    can_move_any_project_to_new_events_table,
    events_table_override,
    project_moved_to_new_events_table,
    use_new_events_schema,
)
from posthog.models.instance_setting import get_instance_setting
from posthog.models.team import Team

from products.feature_flags.backend.facade.enums import FlagEvaluationsMode
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.organization_feature_flags_config import OrganizationFeatureFlagsConfig

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers


def has_active_flags(team: Team) -> bool:
    """Whether the team has an active flag. Remote config sends this as `hasFeatureFlags`, and posthog-js requests
    flags on page load only when it is true. Without an active flag, a browser records no flag call until something
    else loads flags, for example `identify`."""
    # `team=`, not `team_id=`: the flag manager rewrites `team_id=` to the project's root team, which changes the
    # answer for an environment team and costs a join.
    return FeatureFlag.objects.filter(team=team, active=True).exists()


@frozen
class FlagEvaluationsConfig:
    """An organization's flag_evaluations mode, and whether it asks ingestion to keep writing $feature_flag_called to
    events. The second field matters only on FLAG_EVALUATIONS_ONLY."""

    mode: int
    keeps_events_writes: bool

    @property
    def stops_events_writes(self) -> bool:
        """Whether ingestion writes no new flag calls to events for the organization's teams."""
        return self.mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY and not self.keeps_events_writes


# Readers treat an organization without a config row as on EVENTS, with events writes not kept.
NO_ROW_CONFIG = FlagEvaluationsConfig(mode=FlagEvaluationsMode.EVENTS, keeps_events_writes=False)

# The readers' config of an organization whose every team reads the native JSON events table. Node ingestion reads only
# the stored config, so it keeps writing the organization's flag calls to the legacy events table.
NEW_EVENTS_TABLE_READ_CONFIG = FlagEvaluationsConfig(
    mode=FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY, keeps_events_writes=True
)


def get_organization_flag_evaluations_config(organization_id: UUID) -> FlagEvaluationsConfig:
    """The organization's stored config. An organization with no config row reads EVENTS, which matches the COALESCE
    in Node ingestion's team query."""
    row = (
        OrganizationFeatureFlagsConfig.objects.filter(organization_id=organization_id)
        .values_list("flag_evaluations_mode", "keep_writing_flag_calls_to_events")
        .first()
    )
    return NO_ROW_CONFIG if row is None else FlagEvaluationsConfig(mode=row[0], keeps_events_writes=row[1])


def get_organization_flag_evaluations_configs(
    organization_ids: Collection[UUID],
) -> dict[UUID, FlagEvaluationsConfig]:
    """The stored config of each organization, read in one query, with the same EVENTS default as
    get_organization_flag_evaluations_config."""
    stored = {
        organization_id: FlagEvaluationsConfig(mode=mode, keeps_events_writes=keeps_events_writes)
        for organization_id, mode, keeps_events_writes in OrganizationFeatureFlagsConfig.objects.filter(
            organization_id__in=organization_ids
        ).values_list("organization_id", "flag_evaluations_mode", "keep_writing_flag_calls_to_events")
    }
    return {organization_id: stored.get(organization_id, NO_ROW_CONFIG) for organization_id in organization_ids}


def get_organization_flag_evaluations_mode(organization_id: UUID) -> int:
    """The organization's stored FlagEvaluationsMode value."""
    return get_organization_flag_evaluations_config(organization_id).mode


def get_organization_flag_evaluations_modes(organization_ids: Collection[UUID]) -> dict[UUID, int]:
    """The stored FlagEvaluationsMode value of each organization, read in one query."""
    return {
        organization_id: config.mode
        for organization_id, config in get_organization_flag_evaluations_configs(organization_ids).items()
    }


def get_flag_evaluations_read_config(organization_id: UUID, *, team_id: int | None = None) -> FlagEvaluationsConfig:
    """The organization's config with the mode that picks the table for the flag-call readers that the
    READ_FLAG_EVALUATIONS comment lists, with FLAG_EVALUATIONS_READS_FORCE_EVENTS applied.

    An organization below FLAG_EVALUATIONS_ONLY whose every team reads the native JSON events table reads as
    NEW_EVENTS_TABLE_READ_CONFIG. A staff override or the route of the query in progress that picks the legacy events
    table keeps the stored mode, because that table holds every flag call.

    `team_id` names a team of the organization. A caller that holds one passes it, which skips the read of the
    organization's teams when that team still reads the legacy events table."""
    config = get_organization_flag_evaluations_config(organization_id)
    if (
        config.mode != FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY
        and events_table_override(None) is not False
        and (_flag_evaluations_table_enabled_on_every_mode() or config.mode != FlagEvaluationsMode.EVENTS)
        and _organization_reads_new_events_table(organization_id, team_id)
    ):
        config = NEW_EVENTS_TABLE_READ_CONFIG
    return _with_reads_forced_to_events(config)


def get_stored_flag_evaluations_read_config(organization_id: UUID) -> FlagEvaluationsConfig:
    """The organization's stored config with FLAG_EVALUATIONS_READS_FORCE_EVENTS applied. HogQL's catalog and the
    per-team readers below read it, because they check first whether the query or the team reads the native JSON events
    table."""
    return _with_reads_forced_to_events(get_organization_flag_evaluations_config(organization_id))


def get_flag_evaluations_read_mode(organization_id: UUID) -> int:
    """The mode of get_stored_flag_evaluations_read_config."""
    return get_stored_flag_evaluations_read_config(organization_id).mode


def _with_reads_forced_to_events(config: FlagEvaluationsConfig) -> FlagEvaluationsConfig:
    """FLAG_EVALUATIONS_READS_FORCE_EVENTS makes the mode EVENTS for an organization on READ_FLAG_EVALUATIONS, or on
    FLAG_EVALUATIONS_ONLY with its events writes kept, and leaves the stored mode unchanged. HogQL reads flag calls
    from flag_evaluations for a project on the native JSON events table whatever the mode is, because that table holds
    no flag calls, so the switch does not move that project."""
    if not get_instance_setting("FLAG_EVALUATIONS_READS_FORCE_EVENTS"):
        return config
    # Without kept writes, events holds no new flag calls of the teams that ingestion copies to flag_evaluations, so
    # the readers would show no calls instead of the flag_evaluations rows.
    if config.mode == FlagEvaluationsMode.READ_FLAG_EVALUATIONS or (
        config.mode == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY and config.keeps_events_writes
    ):
        return FlagEvaluationsConfig(mode=FlagEvaluationsMode.EVENTS, keeps_events_writes=config.keeps_events_writes)
    return config


def _organization_reads_new_events_table(organization_id: UUID, team_id: int | None) -> bool:
    """Whether every team of the organization, environments included, reads the native JSON events table for every
    reader. A per-request override and the project opt-in move only some reads, so they do not count. An organization
    without teams does not count either."""
    if not can_move_any_project_to_new_events_table():
        return False
    if team_id is not None and not project_moved_to_new_events_table(team_id):
        return False
    other_team_ids = list(
        Team.objects.filter(organization_id=organization_id).exclude(id=team_id).values_list("id", flat=True)
    )
    if team_id is None and not other_team_ids:
        return False
    return all(project_moved_to_new_events_table(other_team_id) for other_team_id in other_team_ids)


def is_flag_calls_union_disabled() -> bool:
    """Whether FLAG_EVALUATIONS_UNION_DISABLED is on. HogQL then reads the flag calls of a query that mixes them with
    other events from events only, for every organization."""
    return bool(get_instance_setting("FLAG_EVALUATIONS_UNION_DISABLED"))


def reads_flag_calls_from_flag_evaluations(team: Team, modifiers: "HogQLQueryModifiers | None" = None) -> bool:
    """Whether a reader that picks its own table reads the team's flag calls from flag_evaluations. A team that reads
    the native JSON events table reads them there on every mode, because that table holds no flag calls. HogQL's
    swap follows the same rule in HogQLContext.reads_flag_calls_from_flag_evaluations."""
    if _reads_native_events_with_flag_evaluations(team, modifiers):
        return True
    return get_flag_evaluations_read_mode(team.organization_id) != FlagEvaluationsMode.EVENTS


def reads_flag_calls_without_events_fallback(team: Team) -> bool:
    """Whether a reader that picks its own table reads the team's flag calls from flag_evaluations alone, as HogQL's
    swap does when it has no fallback to events: the organization is on FLAG_EVALUATIONS_ONLY, whether or not its
    events writes are kept, or the team reads the native JSON events table."""
    if _reads_native_events_with_flag_evaluations(team, None):
        return True
    return get_flag_evaluations_read_mode(team.organization_id) == FlagEvaluationsMode.FLAG_EVALUATIONS_ONLY


def events_lack_new_flag_calls(team: Team, read_config: FlagEvaluationsConfig | None = None) -> bool:
    """Whether a reader that picks its own table finds none of the team's new flag calls in the events table it
    reads: the organization is on FLAG_EVALUATIONS_ONLY without kept events writes, or the team reads the native JSON
    events table. A caller that already holds get_flag_evaluations_read_config for the team's organization passes it
    as `read_config`, which saves the lookup."""
    if _reads_native_events_with_flag_evaluations(team, None):
        return True
    if read_config is None:
        read_config = get_stored_flag_evaluations_read_config(team.organization_id)
    return read_config.stops_events_writes


def _reads_native_events_with_flag_evaluations(team: Team, modifiers: "HogQLQueryModifiers | None") -> bool:
    return use_new_events_schema(team.id, modifiers) and is_flag_evaluations_table_enabled(team)


def hides_flag_calls_from_query_builders(organization_id: UUID, *, team_id: int | None = None) -> bool:
    """Whether the organization's pickers leave out events marked hidden_in_query_builders, and the actions and
    cohorts APIs reject a new use of them. It reads the same mode as the team API's flag_evaluations_mode, which the
    frontend's hiddenEventNames reads, so the pickers and the APIs agree. `team_id` is the hint that
    get_flag_evaluations_read_config takes."""
    return get_flag_evaluations_read_config(organization_id, team_id=team_id).mode != FlagEvaluationsMode.EVENTS


def is_flag_evaluations_table_enabled(team: Team) -> bool:
    """Gate every surface that exposes `posthog.flag_evaluations` through here.

    Reads true on PostHog Cloud for every organization, whatever its flag_evaluations mode. A team on EVENTS
    can query the table, but its flag-call readers still read events. Local dev and end-to-end tests also read
    true. A self-hosted instance reads true only when the organization's mode reads the table.
    """
    # Self-hosted ingestion leaves the flag_evaluations fork off by default, so the table holds no rows there
    # until an operator turns the fork on. The Usage tab reads flag_evaluations for any mode above EVENTS, and
    # its query fails when the table is missing from the catalog.
    return (
        _flag_evaluations_table_enabled_on_every_mode()
        or get_organization_flag_evaluations_mode(team.organization_id) != FlagEvaluationsMode.EVENTS
    )


def _flag_evaluations_table_enabled_on_every_mode() -> bool:
    # PostHog Cloud ingestion forks every team's flag calls into flag_evaluations, so an organization on
    # EVENTS still has rows to query and export.
    # Local and E2E organizations start on EVENTS because FLAG_EVALUATIONS_NEW_ORG_MODE defaults to 0.
    # The table stays queryable there without setting a mode first.
    return is_cloud() or settings.DEBUG or settings.E2E_TESTING
