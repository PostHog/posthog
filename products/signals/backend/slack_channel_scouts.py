"""Scouts that read chosen Slack channels from the data warehouse.

The Slack warehouse source syncs each channel into its own table, named after the channel id, next to the fixed
`$channels` and `$users` tables. A Slack channel scout is a normal scout whose prompt names the tables of the picked
channels, and whose pre-check skips a scheduled run when none of those tables has a new message.

The picked channels live in the scout's own text, so a person can read and edit them on the scout like any other
instruction. The config records the warehouse source the scout reads as its `(source_product, source_id)` owner.
"""

from posthog.dataclasses import frozen

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.signals.backend.enums import SignalSourceProduct
from products.signals.backend.models import SignalScoutConfig
from products.warehouse_sources.backend.facade import api as warehouse_facade
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

SLACK_SCOUT_SOURCE_PRODUCT: str = SignalSourceProduct.SLACK.value
MAX_SLACK_SCOUT_CHANNELS = 20
SLACK_SCOUT_NAME_MAX_LENGTH: int = SignalScoutConfig.MAX_DISPLAY_NAME_LENGTH
# Tables every Slack source syncs. They are not channels.
_FIXED_SLACK_TABLES = frozenset({"$channels", "$users"})


class SlackChannelSelectionError(ValueError):
    pass


@frozen
class SlackChannel:
    id: str
    name: str
    # HogQL name of the channel's message table. None until the channel's first sync writes the table.
    table_name: str | None


@frozen
class SlackChannelSource:
    id: str
    channels: list[SlackChannel]


@frozen
class SlackScoutDefinition:
    description: str
    body: str
    precheck_query: str


def list_slack_channel_sources(team_id: int, user_access_control: UserAccessControl) -> list[SlackChannelSource]:
    """The Slack warehouse sources this caller may view, each with the channels it syncs, ordered by channel name.

    A source or table that an access rule hides from the caller is left out, so neither its channel names nor its
    table names reach the caller or a scout they create.
    """
    slack_sources = [
        source
        for source in warehouse_facade.list_sources(team_id)
        if source.source_type == ExternalDataSourceType.SLACK
    ]
    if not slack_sources:
        return []
    denied_source_ids = set(
        user_access_control.denied_object_ids(
            "external_data_source", [(str(source.id), source.team_id, None) for source in slack_sources], "viewer"
        )
    )
    sources = sorted(
        (source for source in slack_sources if str(source.id) not in denied_source_ids),
        key=lambda source: source.created_at,
    )
    if not sources:
        return []
    # Only a table that is still queryable counts as synced, so a deleted schema or table never reaches the prompt.
    queryable_tables = warehouse_facade.all_queryable_table_keys(team_id)
    denied_table_ids = warehouse_facade.denied_table_ids(team_id, user_access_control)
    result: list[SlackChannelSource] = []
    for source in sources:
        channels = []
        for schema in warehouse_facade.list_schemas_for_source(source.id, team_id):
            if not schema.should_sync or schema.name in _FIXED_SLACK_TABLES or schema.table_id in denied_table_ids:
                continue
            table = queryable_tables.get(schema.table_id) if schema.table_id else None
            channels.append(
                SlackChannel(
                    id=schema.name,
                    name=schema.label or schema.name,
                    table_name=table.queryable_key if table else None,
                )
            )
        result.append(
            SlackChannelSource(id=str(source.id), channels=sorted(channels, key=lambda channel: channel.name.lower()))
        )
    return result


def select_slack_channels(
    sources: list[SlackChannelSource], *, source_id: str, channel_ids: list[str]
) -> list[SlackChannel]:
    """The picked channels of one source, in the order given. Every channel must have synced a table."""
    source = next((source for source in sources if source.id == source_id), None)
    if source is None:
        raise SlackChannelSelectionError("This project has no Slack source with that id.")
    channels = {channel.id: channel for channel in source.channels}
    picked: list[SlackChannel] = []
    for channel_id in dict.fromkeys(channel_ids):
        channel = channels.get(channel_id)
        if channel is None:
            raise SlackChannelSelectionError(f"The Slack source does not sync the channel {channel_id}.")
        if channel.table_name is None:
            raise SlackChannelSelectionError(
                f"#{channel.name} has not synced yet. Pick it again after its first sync finishes."
            )
        picked.append(channel)
    return picked


def build_slack_scout_definition(*, channels: list[SlackChannel], steer: str) -> SlackScoutDefinition:
    """The scout text and pre-check for a set of synced channels."""
    tables = [channel.table_name for channel in channels if channel.table_name]
    if not tables:
        raise SlackChannelSelectionError("Pick at least one synced channel.")
    channel_names = ", ".join(f"#{channel.name}" for channel in channels)
    channel_lines = "\n".join(f"- #{channel.name}: `{channel.table_name}`" for channel in channels)
    focus = steer.strip() or (
        "Bug reports, errors, and broken flows people describe. Feature requests and questions that come up "
        "more than once. Complaints about speed, cost, or confusing behavior."
    )
    body = f"""# Slack channel scout

You read the messages people post in these Slack channels. The PostHog data warehouse syncs each channel into its own
table:

{channel_lines}

Each row is one message. `channel_id` and `ts` identify the message, `timestamp` is when it was posted, `text` is the
message, `user` is the Slack user id of the author, and `thread_ts` groups the replies of a thread. The
`$channels` and `$users` tables of the same source hold the channel and user details.

## What to look for

{focus}

## Each run

1. Read the messages posted since your last run with `execute-sql`, filtered on `timestamp`. Read whole threads, not
   only the first message.
2. Group messages that are about the same problem or request. One message alone is rarely a report. A theme that
   comes up again, or one message that describes a clear, serious problem, can be.
3. Before you file, search the inbox and your scratchpad. Edit the existing report when the theme is already there.
4. File a report only when a person can act on it. Say what people asked for or ran into, how often, and since when.
   Quote short excerpts only. Never copy Slack user ids, names, emails, or other personal details into a report.
5. Keep a scratchpad entry of the themes you have seen, so later runs can tell a new theme from an old one.
"""
    union = " UNION ALL ".join(f"SELECT timestamp FROM {table}" for table in tables)
    # One count over every picked table. A zero count is the single false value that skips the run.
    precheck_query = f"SELECT count() FROM ({union}) WHERE toDateTime(timestamp) > {{since}}"
    return SlackScoutDefinition(
        description=f"Reads {channel_names} in Slack and reports the problems and requests people raise there."[:1000],
        body=body,
        precheck_query=precheck_query,
    )


def plan_slack_channel_scout(
    *, team_id: int, user_access_control: UserAccessControl, source_id: str, channel_ids: list[str], steer: str
) -> SlackScoutDefinition:
    """The scout text and pre-check for the picked channels of one of the team's Slack sources the caller may view."""
    channels = select_slack_channels(
        list_slack_channel_sources(team_id, user_access_control), source_id=source_id, channel_ids=channel_ids
    )
    return build_slack_scout_definition(channels=channels, steer=steer)
