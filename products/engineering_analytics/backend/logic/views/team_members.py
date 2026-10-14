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


def build_roster_query(table_name: str, *, has_role: bool) -> str:
    """One row per (member, team), for reading the roster itself rather than joining PR authors to it.

    Logins are lowercased here because a reader matches them against identities stored lowercase.
    A snapshot without the optional ``role`` column reports every member as a plain member, which is
    the honest answer: the column's absence says nothing about who maintains the team.

    Membership is org-scoped but the source offers it per repo, so one membership can land more than
    once. The grouping collapses those to one row, and ``max`` keeps a maintainer row winning over a
    plain-member duplicate of the same membership.
    """
    is_maintainer = "lower(ifNull(role, '')) = 'maintainer'" if has_role else "0"
    return f"""
        SELECT
            lower(ifNull(login, '')) AS member_handle,
            ifNull(team_slug, '') AS team_slug,
            max(ifNull(team_name, '')) AS team_name,
            max({is_maintainer}) AS is_maintainer
        FROM {table_name}
        WHERE ifNull(login, '') != '' AND ifNull(team_slug, '') != ''
        GROUP BY member_handle, team_slug
    """
