"""Writes each ranked observation's narrow rank row, which the highlight feed reads instead of the observation.

The person key and experiment scope come from the observation row inside the same statement, so every writer derives
them the same way.
"""

import uuid
from collections.abc import Mapping
from itertools import batched
from typing import Any

from django.db import connection

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.replay_vision.backend.models.replay_observation_rank import RankCategory
from products.replay_vision.backend.scope.load import EXPERIMENT_ID_SNAPSHOT_STORES

_WRITE_CHUNK = 500

CATEGORY_CODES: dict[str, int] = {category.name.lower(): category.value for category in RankCategory}
CATEGORY_NAMES: dict[int, str] = {code: name for name, code in CATEGORY_CODES.items()}


# A snapshot that names an experiment as anything but a plain integer gets -1, which matches no experiment, so the row
# stays hidden from every viewer rather than readable by all.
def _experiment_sql() -> str:
    """The rank row's denormalized experiment id, read from every store a snapshot can hold it in.

    0 means the scan watched no experiment, which the readable-rank filters treat as readable by
    anyone. A store left out of this CASE would give a snapshot held only in that store a 0 and
    make its rows public, so the branches are generated from the shared store list rather than
    typed out. -1 means a store named something this column cannot hold, which is readable by
    nobody.

    `experiment_id` is written once, when the rank row is inserted: `record_ranks` leaves it out of
    its ON CONFLICT update and `_has_current_rank` skips an observation that already has a row. A
    row computed without a store keeps its wrong value, so this has to be right before the first
    observation of a scanner using that store is ranked.
    """
    numeric = "\n".join(
        f"""        WHEN o.scanner_snapshot #>> '{{{store},experiment_id}}' ~ '^-?[0-9]{{1,9}}$'
            THEN (o.scanner_snapshot #>> '{{{store},experiment_id}}')::int"""
        for store in EXPERIMENT_ID_SNAPSHOT_STORES
    )
    present = "\n            OR ".join(
        f"o.scanner_snapshot #> '{{{store},experiment_id}}' IS NOT NULL" for store in EXPERIMENT_ID_SNAPSHOT_STORES
    )
    return f"""
    CASE
{numeric}
        WHEN {present}
            THEN -1
        ELSE 0
    END
"""


_EXPERIMENT_SQL = _experiment_sql()
_PERSON_SQL = "hashtextextended(COALESCE(NULLIF(o.distinct_id, ''), o.session_id), 0)"
_RANK_COLUMNS = (
    "observation_id, team_id, scanner_id, created_at, anchor_version, contrast, category, feed_group_id, "
    "search_theme_id, person_key, experiment_id"
)


@frozen
class NewRank:
    contrast: float
    category: str


def record_ranks(team_id: int, anchor_version: int, ranks: Mapping[str, NewRank]) -> int:
    """Write a rank row for each ranked observation, in the caller's transaction. An observation that already has one
    under `anchor_version` keeps it, so a redelivered message changes nothing, and one ranked under other anchors is
    ranked afresh, clusters included. Returns how many rows it wrote."""
    row_team_id = resolve_effective_team_id(team_id)
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
                SELECT o.id, %s, o.scanner_id, o.created_at, %s, r.contrast, r.category, NULL, NULL,
                    {_PERSON_SQL}, {_EXPERIMENT_SQL}
                FROM (VALUES {values}) AS r(observation_id, contrast, category)
                JOIN replay_vision_replayobservation o ON o.id = r.observation_id AND o.team_id = %s
                ON CONFLICT (observation_id) DO UPDATE SET
                    anchor_version = EXCLUDED.anchor_version,
                    contrast = EXCLUDED.contrast,
                    category = EXCLUDED.category,
                    feed_group_id = NULL,
                    search_theme_id = NULL,
                    ranked_at = now()
                WHERE replay_vision_replayobservationrank.anchor_version <> EXCLUDED.anchor_version
                """,
                [row_team_id, anchor_version, *params, team_id],
            )
            inserted += cursor.rowcount
    if inserted:
        mark_changed(team_id)
    return inserted


def set_rank_clusters(team_id: int, clusters: Mapping[str, tuple[uuid.UUID, uuid.UUID | None]]) -> None:
    """Record each observation's feed group and search theme on its rank row."""
    row_team_id = resolve_effective_team_id(team_id)
    updated = 0
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
                [*params, row_team_id],
            )
            updated += cursor.rowcount
    if updated:
        mark_changed(team_id)


def mark_changed(team_id: int) -> None:
    """Ask for a rebuild of the team's highlight feed, in the caller's transaction. Every ask counts, so one that lands
    while a build ranks is still due after it; a build never holds the state row while it ranks."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO replay_vision_replayhighlightfeedstate (team_id, generation, builds, changes, built_changes)
            VALUES (%s, 0, '[]'::jsonb, 1, 0)
            ON CONFLICT (team_id) DO UPDATE SET changes = replay_vision_replayhighlightfeedstate.changes + 1
            """,
            [resolve_effective_team_id(team_id)],
        )
