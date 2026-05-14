"""Find Error Tracking issues whose recent events implicate code in this PR.

Two-step query:
  1. HogQL on `$exception` events in the lookback window, filtered by a
     ClickHouse `multiSearchAny` over the concatenated exception payload
     (stack trace + message + raw frames). Returns per-issue counts and
     a sample message.
  2. Django lookup on ``ErrorTrackingIssue`` to enrich each match with
     name + status.

Search terms include:
  - Each changed file's basename (stack frames usually contain at least
    that much) — short paths are skipped to avoid trivial matches.
  - Each matched flag key / event name — catches issues where the flag
    or event itself is mentioned in the exception message.
"""

import os
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from products.error_tracking.backend.models import ErrorTrackingIssue

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import IssueReference


# Below this length, file basenames / key terms produce noisy substring matches
# against arbitrary text inside exception payloads.
_MIN_TERM_LEN = 4
_MAX_ISSUES = 25


def _build_search_terms(changed_files: list[str], key_terms: list[str]) -> list[str]:
    """Build a deduplicated list of distinctive substrings to search for.

    For each changed file we contribute the basename (most likely to
    appear in stack frames) and a longer path tail (handles namespaced
    bundlers). Empty / too-short terms are filtered out.
    """
    out: set[str] = set()
    for path in changed_files:
        if not path:
            continue
        basename = os.path.basename(path)
        if basename and len(basename) >= _MIN_TERM_LEN:
            out.add(basename)
        # Last two path segments give us a bit more uniqueness for common
        # filenames like `index.ts` or `service.py`.
        parts = path.split("/")
        if len(parts) >= 2:
            tail = "/".join(parts[-2:])
            if len(tail) >= _MIN_TERM_LEN:
                out.add(tail)

    for term in key_terms:
        if term and len(term) >= _MIN_TERM_LEN:
            out.add(term)

    return sorted(out)


def find_referencing_issues(
    team: "Team",
    changed_files: list[str],
    key_terms: list[str],
    lookback_days: int,
) -> list["IssueReference"]:
    """Return Error Tracking issues whose recent $exception events implicate the PR."""
    from ..facade.contracts import IssueReference

    terms = _build_search_terms(changed_files, key_terms)
    if not terms:
        return []

    # Concatenate the exception properties most likely to contain file paths,
    # then run multiSearchAny against the term list. Cheap relative to a
    # per-term LIKE chain, and works as long as the SDK populated any of
    # these properties on capture.
    # Per-row haystack (CTE-style aliasing isn't available, so the concat is
    # repeated in the SELECT and WHERE — ClickHouse will dedupe at planning).
    # The per-row "which terms matched this event" is computed inside the row
    # context, then unioned across the group via groupArrayArray + arrayDistinct
    # so each issue gets the set of terms its events collectively matched.
    # nosemgrep: hogql-fstring (no f-string interpolation in query body)
    response = execute_hogql_query(
        query="""
            SELECT
                toString(properties.$exception_issue_id) AS issue_id,
                count() AS occurrences,
                uniq(person_id) AS users,
                any(toString(properties.$exception_message)) AS sample_message,
                groupUniqArrayArray(
                    arrayFilter(
                        t -> position(
                            concat(
                                toString(properties.$exception_list), ' ',
                                toString(properties.$exception_stack_trace_raw), ' ',
                                toString(properties.$exception_message), ' ',
                                toString(properties.$exception_type)
                            ),
                            t
                        ) > 0,
                        {terms}
                    )
                ) AS matched
            FROM events
            WHERE event = '$exception'
              AND timestamp > now() - toIntervalDay({lookback_days})
              AND notEmpty(toString(properties.$exception_issue_id))
              AND multiSearchAny(
                  concat(
                      toString(properties.$exception_list), ' ',
                      toString(properties.$exception_stack_trace_raw), ' ',
                      toString(properties.$exception_message), ' ',
                      toString(properties.$exception_type)
                  ),
                  {terms}
              ) > 0
            GROUP BY issue_id
            ORDER BY occurrences DESC
            LIMIT {limit}
        """,
        team=team,
        placeholders={
            "lookback_days": ast.Constant(value=lookback_days),
            "limit": ast.Constant(value=_MAX_ISSUES),
            "terms": ast.Array(exprs=[ast.Constant(value=t) for t in terms]),
        },
    )

    rows = response.results or []
    if not rows:
        return []

    issue_ids: list[str] = []
    per_issue: dict[str, dict] = {}
    for row in rows:
        issue_id, occurrences, users, sample_message, matched = row
        if not issue_id:
            continue
        issue_ids.append(issue_id)
        per_issue[issue_id] = {
            "occurrences": int(occurrences or 0),
            "users": int(users or 0),
            "sample_message": (sample_message or "").strip()[:280],
            "matched_terms": tuple(sorted(matched or [])),
        }

    # Pull names + status from Postgres in one shot. Issues whose ClickHouse
    # rows reference IDs that no longer exist in Postgres (deletion, drift)
    # are silently skipped.
    issues = {str(i.id): i for i in ErrorTrackingIssue.objects.filter(team=team, id__in=issue_ids)}

    out: list[IssueReference] = []
    for issue_id in issue_ids:
        django_issue = issues.get(issue_id)
        if django_issue is None:
            continue
        data = per_issue[issue_id]
        out.append(
            IssueReference(
                id=issue_id,
                name=(django_issue.name or "Untitled issue").strip()[:200],
                status=str(django_issue.status),
                occurrences=data["occurrences"],
                users_affected=data["users"],
                sample_message=data["sample_message"],
                matched_terms=data["matched_terms"],
            )
        )
    return out
