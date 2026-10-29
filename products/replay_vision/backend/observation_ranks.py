"""Writes each ranked observation's narrow rank row, which the highlight feed reads instead of the observation.

The person key and experiment scope come from the observation row inside the same statement, so every writer derives
them the same way.
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from itertools import batched
from typing import Any

from django.db import connection

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.replay_vision.backend.models.replay_observation_rank import RankCategory

_WRITE_CHUNK = 500

CATEGORY_CODES: dict[str, int] = {
    "failure": RankCategory.FAILURE,
    "struggle": RankCategory.STRUGGLE,
    "revenue": RankCategory.REVENUE,
    "routine": RankCategory.ROUTINE,
}

# A snapshot that names an experiment it cannot parse gets -1, which matches no experiment, so the row stays hidden
# from every viewer rather than readable by all.
_EXPERIMENT_SQL = """
    CASE
        WHEN jsonb_typeof(o.scanner_snapshot #> '{experiment_targeting,experiment_id}') = 'number'
            THEN (o.scanner_snapshot #>> '{experiment_targeting,experiment_id}')::int
        WHEN jsonb_typeof(o.scanner_snapshot #> '{scanner_config,experiment_id}') = 'number'
            THEN (o.scanner_snapshot #>> '{scanner_config,experiment_id}')::int
        WHEN o.scanner_snapshot #> '{experiment_targeting,experiment_id}' IS NOT NULL
            OR o.scanner_snapshot #> '{scanner_config,experiment_id}' IS NOT NULL
            THEN -1
        ELSE 0
    END
"""
_PERSON_SQL = "hashtextextended(COALESCE(NULLIF(o.distinct_id, ''), o.session_id), 0)"
_RANK_COLUMNS = (
    "observation_id, team_id, scanner_id, created_at, anchor_version, contrast, category, feed_group_id, "
    "search_theme_id, person_key, experiment_id"
)
_MARK_CHANGED_SQL = """
    INSERT INTO replay_vision_replayhighlightfeedstate (team_id, generation, changed_at)
    VALUES (%s, 0, now())
    ON CONFLICT (team_id) DO UPDATE SET changed_at = EXCLUDED.changed_at
    WHERE replay_vision_replayhighlightfeedstate.changed_at IS NULL
        OR replay_vision_replayhighlightfeedstate.changed_at <= replay_vision_replayhighlightfeedstate.built_at
"""


@frozen
class NewRank:
    contrast: float
    category: str


def record_ranks(team_id: int, anchor_version: int, ranks: Mapping[str, NewRank]) -> int:
    """Insert a rank row for each newly ranked observation, in the caller's transaction. An observation that already
    has one keeps it, so a redelivered message changes nothing. Returns how many rows it inserted."""
    inserted = 0
    for chunk in batched(ranks.items(), _WRITE_CHUNK, strict=False):
        params: list[Any] = []
        for observation_id, rank in chunk:
            params += [observation_id, rank.contrast, CATEGORY_CODES[rank.category]]
        values = ", ".join(["(%s::uuid, %s::double precision, %s::smallint)"] * len(chunk))
        with connection.cursor() as cursor:
            cursor.execute(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
                f"""
                INSERT INTO replay_vision_replayobservationrank ({_RANK_COLUMNS})
                SELECT o.id, o.team_id, o.scanner_id, o.created_at, %s, r.contrast, r.category, NULL, NULL,
                    {_PERSON_SQL}, {_EXPERIMENT_SQL}
                FROM (VALUES {values}) AS r(observation_id, contrast, category)
                JOIN replay_vision_replayobservation o ON o.id = r.observation_id AND o.team_id = %s
                ON CONFLICT (observation_id) DO NOTHING
                """,
                [anchor_version, *params, team_id],
            )
            inserted += cursor.rowcount
    if inserted:
        _mark_changed(team_id)
    return inserted


def set_rank_clusters(team_id: int, clusters: Mapping[str, tuple[uuid.UUID, uuid.UUID | None]]) -> None:
    """Record each observation's feed group and search theme on its rank row."""
    for chunk in batched(clusters.items(), _WRITE_CHUNK, strict=False):
        params: list[Any] = []
        for observation_id, (group_id, theme_id) in chunk:
            params += [observation_id, group_id, theme_id]
        values = ", ".join(["(%s::uuid, %s::uuid, %s::uuid)"] * len(chunk))
        with connection.cursor() as cursor:
            cursor.execute(
                # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
                f"""
                UPDATE replay_vision_replayobservationrank rank
                SET feed_group_id = c.group_id, search_theme_id = COALESCE(c.theme_id, rank.search_theme_id)
                FROM (VALUES {values}) AS c(observation_id, group_id, theme_id)
                WHERE rank.observation_id = c.observation_id AND rank.team_id = %s
                """,
                [*params, team_id],
            )
    if clusters:
        _mark_changed(team_id)


def copy_team_ranks(team_id: int, anchor_version: int, since: datetime, *, dry_run: bool = False) -> int:
    """Copy the team's current ranks since `since` from the observations' rank JSON into rank rows, filling in a
    feed group or search theme an existing row lacks. Returns how many rows it wrote, or would write."""
    source = """
        FROM replay_vision_replayobservation o
        WHERE o.team_id = %(team_id)s
            AND o.created_at >= %(since)s
            AND o.status = 'succeeded'
            AND o.watch_rank IS NOT NULL
            AND o.watch_rank -> 'anchor_version' = to_jsonb(%(anchor_version)s::int)
            AND jsonb_typeof(o.watch_rank -> 'contrast') = 'number'
            AND o.watch_rank ->> 'category' IN ('failure', 'struggle', 'revenue', 'routine')
    """
    category = "CASE o.watch_rank ->> 'category' " + " ".join(
        f"WHEN '{name}' THEN {code}" for name, code in CATEGORY_CODES.items()
    )
    params: dict[str, Any] = {
        "team_id": resolve_effective_team_id(team_id),
        "since": since,
        "anchor_version": anchor_version,
    }
    with connection.cursor() as cursor:
        if dry_run:
            # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
            cursor.execute(f"SELECT count(*) {source}", params)
            return cursor.fetchone()[0]
        cursor.execute(
            # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (fixed SQL, every value is a parameter)
            f"""
            INSERT INTO replay_vision_replayobservationrank ({_RANK_COLUMNS})
            SELECT o.id, o.team_id, o.scanner_id, o.created_at, %(anchor_version)s,
                (o.watch_rank ->> 'contrast')::double precision, {category} END,
                (o.watch_rank ->> 'group')::uuid, (o.watch_rank ->> 'theme')::uuid,
                {_PERSON_SQL}, {_EXPERIMENT_SQL}
            {source}
            ON CONFLICT (observation_id) DO UPDATE SET
                feed_group_id = COALESCE(replay_vision_replayobservationrank.feed_group_id, EXCLUDED.feed_group_id),
                search_theme_id = COALESCE(replay_vision_replayobservationrank.search_theme_id, EXCLUDED.search_theme_id)
            WHERE (replay_vision_replayobservationrank.feed_group_id IS NULL AND EXCLUDED.feed_group_id IS NOT NULL)
                OR (replay_vision_replayobservationrank.search_theme_id IS NULL AND EXCLUDED.search_theme_id IS NOT NULL)
            """,
            params,
        )
        written = cursor.rowcount
    if written:
        _mark_changed(team_id)
    return written


def _mark_changed(team_id: int) -> None:
    # Only the first change after a build writes, so a busy team does not rewrite its state row on every rank.
    with connection.cursor() as cursor:
        cursor.execute(_MARK_CHANGED_SQL, [resolve_effective_team_id(team_id)])
