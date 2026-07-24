"""Curated GitHub org team-membership query builder.

Maps the raw ``team_members`` warehouse snapshot (GitHub member user objects with the
parent team's identity injected by the source's fan-out) into the two columns the
membership join needs: the member's login and the GitHub team slug. This is the only
place membership columns are mapped; the table name is resolved per-team and passed in
(see ``logic.sources``), never hardcoded.

The snapshot lands every column ``Nullable`` (see ``source_schema.py``), so each read
is ``ifNull``-guarded to keep the curated columns non-null strings. Rows without a login
are dropped: an empty ``member_handle`` would match deleted-account PR authors.
"""


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            ifNull(login, '') AS member_handle,
            ifNull(team_slug, '') AS team_slug
        FROM {table_name}
        WHERE ifNull(login, '') != ''
    """
