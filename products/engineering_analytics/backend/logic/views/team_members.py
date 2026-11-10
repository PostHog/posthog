def build_query(table_name: str) -> str:
    # Rows without a login are dropped, because an empty member_handle would match the empty author of
    # a pull request from a deleted account.
    return f"""
        SELECT
            ifNull(login, '') AS member_handle,
            ifNull(team_slug, '') AS team_slug
        FROM {table_name}
        WHERE ifNull(login, '') != ''
    """


def build_roster_query(table_name: str, *, has_role: bool) -> str:
    """One row per (member, team), with ``member_handle`` lowercased.

    ``is_maintainer`` is 0 for every member when the table has no ``role`` column. The source lands one
    membership once per repo, so the grouping collapses the duplicates.
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
