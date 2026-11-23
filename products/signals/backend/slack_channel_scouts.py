"""Scouts that read chosen Slack channels from the data warehouse.

The Slack warehouse source syncs each channel into its own table, named after the channel id, next to the fixed
`$channels` and `$users` tables. A Slack channel scout is a normal scout whose prompt names the tables of the picked
channels, and whose pre-check skips a scheduled run when none of those tables has a new message.

The picked channels live in the scout's own text, so a person can read and edit them on the scout like any other
instruction. The config records the warehouse source the scout reads as its `(source_product, source_id)` owner.
"""

from django.db.models import Q

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.dataclasses import frozen

from products.signals.backend.enums import SignalSourceProduct
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

SLACK_SCOUT_SOURCE_PRODUCT = SignalSourceProduct.SLACK.value
MAX_SLACK_SCOUT_CHANNELS = 20
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


def list_slack_channel_sources(team_id: int) -> list[SlackChannelSource]:
    """The team's Slack warehouse sources, each with the channels it syncs, ordered by channel name."""
    sources = list(
        ExternalDataSource.objects.filter(team_id=team_id, source_type=ExternalDataSourceType.SLACK)
        .exclude(deleted=True)
        .order_by("created_at")
    )
    schemas = (
        ExternalDataSchema.objects.filter(team_id=team_id, source__in=sources, should_sync=True)
        .exclude(deleted=True)
        .exclude(name__in=_FIXED_SLACK_TABLES)
        .exclude(Q(table__isnull=False) & Q(table__deleted=True))
        .select_related("table")
    )
    channels_by_source: dict[str, list[SlackChannel]] = {str(source.id): [] for source in sources}
    sources_by_id = {str(source.id): source for source in sources}
    for schema in schemas:
        source = sources_by_id[str(schema.source_id)]
        channels_by_source[str(source.id)].append(
            SlackChannel(
                id=schema.name,
                name=schema.label or schema.name,
                table_name=get_data_warehouse_table_name(source, schema.table.name) if schema.table else None,
            )
        )
    return [
        SlackChannelSource(id=source_id, channels=sorted(channels, key=lambda channel: channel.name.lower()))
        for source_id, channels in channels_by_source.items()
    ]


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
