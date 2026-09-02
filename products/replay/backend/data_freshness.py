from datetime import datetime

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.data_freshness import CLICKHOUSE_SETTINGS, DataSourceSpec, ProbeWindow
from posthog.schema_enums import ProductKey
from posthog.utils import ensure_utc


def _max_between(team_ids: list[int], since: datetime, until: datetime) -> dict[int, datetime]:
    with tags_context(product=Product.REPLAY, feature=Feature.DATA_FRESHNESS):
        rows = sync_execute(
            """
            SELECT team_id, max(min_first_timestamp)
            FROM session_replay_events
            WHERE team_id IN %(team_ids)s
              AND min_first_timestamp >= %(since)s
              AND min_first_timestamp < %(until)s
            GROUP BY team_id
            """,
            {"team_ids": team_ids, "since": since, "until": until},
            settings=CLICKHOUSE_SETTINGS,
        )
    return {team_id: ensure_utc(last_data_at) for team_id, last_data_at in rows}


def last_replay_at(team_ids: list[int], window: ProbeWindow) -> dict[int, datetime]:
    """Ask for the recent window first, then only widen for teams that came back empty.

    `session_replay_events` sorts on `(toDate(min_first_timestamp), team_id, session_id)`, so
    unlike the shared queries its bytes scale with the window as well as the team count.
    Splitting it means a busy team, which is where the bytes are, is answered from the short
    window and its older tail is never read. The teams that do need the wider read are by
    definition the ones with nothing recent.
    """
    found = _max_between(team_ids, window.quiet_before, window.horizon)

    older = [team_id for team_id in team_ids if team_id not in found]
    if older:
        found |= _max_between(older, window.cutoff, window.quiet_before)
    return found


DATA_SOURCES = [DataSourceSpec(product=ProductKey.SESSION_REPLAY, probe=last_replay_at)]
