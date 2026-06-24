"""Ordered, paginated resolution of the inbox report list.

The inbox list sorts on derived, latest-wins status artefacts — current priority
(`priority_judgment`) and the ready/not-actionable split (`actionability_judgment`).
Expressing those as correlated subqueries (one per ordering field, per row) makes the
sort touch the artefact table once for *every* report in the team's set — a full-set
scan of random index seeks that is fine on a warm cache but turns into multi-second
cold-cache I/O on large teams (the inbox's 20s loads).

This module resolves each latest-wins value *once* via a `DISTINCT ON` join, then sorts
the joined result — a couple of bounded index scans plus a hash join instead of N seeks.
Ordering semantics are identical to the old correlated form; only the plan shape changes.

The supporting index is `signals_signalreportartefact (team_id, type, report_id,
created_at DESC)`.
"""

from __future__ import annotations

from django.db import connection

from products.signals.backend.models import SignalReport

# status -> semantic pipeline rank (lower sorts earlier in the inbox). `ready` splits into
# rank 0 (actionable, or not yet judged) and rank 1 (not actionable) via the latest
# actionability judgment. Single source of truth for both the ORM annotation
# (`_annotate_signal_report_status_rank`, used by non-list actions) and the SQL below.
STATUS_RANK: dict[str, int] = {
    SignalReport.Status.READY: 0,
    SignalReport.Status.PENDING_INPUT: 2,
    SignalReport.Status.IN_PROGRESS: 3,
    SignalReport.Status.CANDIDATE: 4,
    SignalReport.Status.POTENTIAL: 5,
    SignalReport.Status.FAILED: 6,
    SignalReport.Status.RESOLVED: 7,
    SignalReport.Status.SUPPRESSED: 8,
    SignalReport.Status.DELETED: 9,
}
READY_NOT_ACTIONABLE_RANK = 1
STATUS_RANK_DEFAULT = 50
PRIORITY_FALLBACK = "~"  # sorts after P0–P4 for reports without a priority judgment


def _status_rank_sql() -> str:
    # Built from STATUS_RANK so it can't drift from the ORM annotation. `status` values are
    # enum constants, never user input, so this CASE is safe to interpolate.
    whens = [
        f"WHEN r.status='{SignalReport.Status.READY}' AND la.actionability='not_actionable' "
        f"THEN {READY_NOT_ACTIONABLE_RANK}"
    ]
    whens += [f"WHEN r.status='{status}' THEN {rank}" for status, rank in STATUS_RANK.items()]
    return "CASE " + " ".join(whens) + f" ELSE {STATUS_RANK_DEFAULT} END"


def _priority_sql() -> str:
    return f"COALESCE(lp.priority, '{PRIORITY_FALLBACK}')"


def _is_suggested_reviewer_sql(has_github_login: bool) -> str:
    # Mirrors `_annotate_is_suggested_reviewer`: never true for ready+not-actionable or failed
    # reports; otherwise true when the current user is in the latest suggested_reviewers artefact.
    # The containment value is bound as a parameter (one `%s`) when `has_github_login`.
    if not has_github_login:
        return "false"
    reviewer_exists = (
        "EXISTS(SELECT 1 FROM signals_signalreportartefact v0 "
        "WHERE v0.report_id=r.id AND v0.type='suggested_reviewers' "
        "AND NOT EXISTS(SELECT 1 FROM signals_signalreportartefact u0 "
        "WHERE u0.report_id=v0.report_id AND u0.type='suggested_reviewers' AND u0.created_at>v0.created_at) "
        "AND v0.content::jsonb @> %s::jsonb)"
    )
    return (
        f"CASE WHEN r.status='{SignalReport.Status.READY}' AND la.actionability='not_actionable' THEN false "
        f"WHEN r.status='{SignalReport.Status.FAILED}' THEN false ELSE {reviewer_exists} END"
    )


# Ordering field -> (sort expression, whether it consumes the github_login param). A None
# expression is a no-op sort key to drop entirely — used when is_suggested_reviewer can't be
# resolved (no github login), where every row is False and the key would be a bare SQL constant
# (which Postgres rejects in ORDER BY) that contributes nothing to the order anyway.
def _order_expr(field: str, has_github_login: bool) -> tuple[str | None, bool]:
    if field == "status":
        return _status_rank_sql(), False
    if field == "priority":
        return _priority_sql(), False
    if field == "is_suggested_reviewer":
        if not has_github_login:
            return None, False
        return _is_suggested_reviewer_sql(True), True
    # Remaining fields are plain report columns, validated against the allowlist upstream.
    return f"r.{field}", False


# DISTINCT ON join that resolves the latest value of one jsonb key from a latest-wins status
# artefact type. team_id + type are bound parameters; `key` and `type` are fixed constants.
def _latest_value_cte(alias: str, artefact_type: str, json_key: str, out_col: str) -> str:
    return (
        f"{alias} AS (SELECT DISTINCT ON (report_id) report_id, "
        f"jsonb_extract_path_text(content::jsonb, '{json_key}') AS {out_col} "
        f"FROM signals_signalreportartefact "
        f"WHERE team_id=%s AND type='{artefact_type}' AND content LIKE '{{%%' "
        f"ORDER BY report_id, created_at DESC)"
    )


def resolve_ordered_report_page(
    *,
    team_id: int,
    base_ids_sql: str,
    base_ids_params: list,
    order_fields: list[tuple[str, bool]],  # (field, descending)
    github_login: str | None,
    actionability_filter: list[str] | None,
    priority_filter: list[str] | None,
    reviewer_containment_param: str | None,
    limit: int,
    offset: int,
) -> tuple[list[str], int]:
    """Return (ordered page of report ids, total count) for the filtered set.

    `base_ids_sql` / `base_ids_params` is a queryset selecting `id` with every filter that does
    not depend on the latest-wins artefacts already applied. The actionability / priority filters
    are applied here against the joined values so they share the single resolution.
    """
    has_login = github_login is not None

    ctes = [
        f"base AS ({base_ids_sql})",
        _latest_value_cte("latest_prio", "priority_judgment", "priority", "priority"),
        _latest_value_cte("latest_act", "actionability_judgment", "actionability", "actionability"),
    ]
    from_join = (
        "FROM signals_signalreport r "
        "JOIN base ON base.id = r.id "
        "LEFT JOIN latest_prio lp ON lp.report_id = r.id "
        "LEFT JOIN latest_act la ON la.report_id = r.id"
    )

    where_parts: list[str] = []
    where_params: list = []
    if actionability_filter:
        where_parts.append("la.actionability = ANY(%s)")
        where_params.append(actionability_filter)
    if priority_filter:
        where_parts.append(f"{_priority_sql()} = ANY(%s)")
        where_params.append(priority_filter)
    where_sql = (" WHERE " + " AND ".join(where_parts)) if where_parts else ""

    order_terms: list[str] = []
    order_params: list = []
    for field, descending in order_fields:
        expr, uses_login = _order_expr(field, has_login)
        if expr is None:
            continue
        order_terms.append(f"({expr}) {'DESC' if descending else 'ASC'}")
        if uses_login and reviewer_containment_param is not None:
            order_params.append(reviewer_containment_param)
    order_sql = ", ".join(order_terms)

    # Parameter order must match textual placeholder order: base CTE, the two latest-value
    # CTEs (team_id each), WHERE (derived filters), ORDER BY (reviewer containment), LIMIT/OFFSET.
    cte_sql = "WITH " + ", ".join(ctes)

    page_sql = f"{cte_sql} SELECT r.id::text {from_join}{where_sql} ORDER BY {order_sql} LIMIT %s OFFSET %s"
    page_params = [
        *base_ids_params,
        team_id,
        team_id,
        *where_params,
        *order_params,
        limit,
        offset,
    ]

    with connection.cursor() as cursor:
        cursor.execute(page_sql, page_params)
        ids = [row[0] for row in cursor.fetchall()]

        if where_parts:
            # Derived filters need the joins to count; reuse the same CTEs without order/paging.
            count_sql = f"{cte_sql} SELECT COUNT(*) {from_join}{where_sql}"
            count_params = [*base_ids_params, team_id, team_id, *where_params]
            cursor.execute(count_sql, count_params)
        else:
            # No derived filter -> count the filtered base directly (indexable, no artefact joins).
            cursor.execute(f"SELECT COUNT(*) FROM ({base_ids_sql}) base", base_ids_params)
        total = cursor.fetchone()[0]

    return ids, total
