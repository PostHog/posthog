"""Fetch full survey response rows (with metadata) for the responses API.

The summarization fetch helper returns response strings only — sufficient for LLM
input but not for agents that need to cross-pivot to recordings, events, or persons.
This module returns rows with `distinct_id`, `session_id`, `submitted_at`, resolved
per-question answers, and event-level metadata (device, geoip, etc).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team

from products.surveys.backend.models import Survey


@dataclass(frozen=True)
class QuestionAnswer:
    question_id: str
    question_index: int
    question_text: str
    question_type: str
    answer: Any


@dataclass(frozen=True)
class SurveyResponseRow:
    uuid: str
    distinct_id: str
    session_id: str | None
    submitted_at: datetime
    answers: list[QuestionAnswer]
    extra: dict[str, Any] = field(default_factory=dict)


def resolve_question_metadata(survey: Survey) -> list[dict[str, Any]]:
    """Return survey questions with stable `(id, index, text, type, choices)` shape."""
    questions = survey.questions or []
    resolved: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        resolved.append(
            {
                "id": question.get("id") or "",
                "index": index,
                "text": question.get("question") or "",
                "type": question.get("type") or "open",
                "choices": question.get("choices"),
            }
        )
    return resolved


# Metadata columns appended to every row — known $-prefixed event properties resolved via
# HogQL property accessors (backticked because the keys are literal property names, not
# placeholder values).
_METADATA_COLUMNS: list[tuple[str, str]] = [
    ("session_id", "properties.`$session_id`"),
    ("device_type", "properties.`$device_type`"),
    ("browser", "properties.`$browser`"),
    ("os", "properties.`$os`"),
    ("geoip_country_code", "properties.`$geoip_country_code`"),
    ("geoip_country_name", "properties.`$geoip_country_name`"),
    ("geoip_city_name", "properties.`$geoip_city_name`"),
    ("current_url", "properties.`$current_url`"),
    ("iteration", "properties.`$survey_iteration`"),
]


def fetch_response_rows(
    *,
    survey: Survey,
    team: Team,
    since: datetime | None = None,
    until: datetime | None = None,
    question_id: str | None = None,
    score_lte: float | None = None,
    score_gte: float | None = None,
    limit: int = 100,
    offset: int = 0,
    exclude_uuids: set[str] | None = None,
) -> tuple[list[SurveyResponseRow], bool]:
    """Fetch survey response rows for the responses API.

    `score_lte` / `score_gte` require `question_id` — score filtering only
    makes sense against a specific rating question.
    """
    if (score_lte is not None or score_gte is not None) and not question_id:
        raise ValueError("score_lte / score_gte require question_id")

    survey_id = str(survey.id)
    questions = resolve_question_metadata(survey)

    questions_in_scope = [q for q in questions if (not question_id or q["id"] == question_id)]
    if question_id and not questions_in_scope:
        return [], False

    paginator = HogQLHasMorePaginator(limit=limit, offset=offset)

    placeholders: dict[str, ast.Expr] = {
        "survey_id": ast.Constant(value=survey_id),
        # uniqueSurveySubmissionsFilter requires bounded dates — fall back to
        # the survey lifetime when the caller didn't supply explicit bounds.
        "start_date": ast.Constant(value=since or survey.start_date or survey.created_at),
        "end_date": ast.Constant(value=until or survey.end_date or datetime.now(UTC)),
    }

    # Dynamically add one column per question using the HogQL getSurveyResponse helper —
    # the same helper the summarization fetch uses, so the resolution semantics match.
    answer_columns: list[str] = []
    for q in questions_in_scope:
        idx_name = f"q_idx_{q['index']}"
        id_name = f"q_id_{q['index']}"
        answer_columns.append(f"getSurveyResponse({{{idx_name}}}, {{{id_name}}}) AS answer_{q['index']}")
        placeholders[idx_name] = ast.Constant(value=q["index"])
        placeholders[id_name] = ast.Constant(value=q["id"])

    select_clause = ", ".join(
        [
            "uuid",
            "distinct_id",
            "timestamp AS submitted_at",
            *(f"{expr} AS {alias}" for alias, expr in _METADATA_COLUMNS),
            *answer_columns,
        ]
    )

    conditions = [
        "event = 'survey sent'",
        "properties.`$survey_id` = {survey_id}",
        "uniqueSurveySubmissionsFilter({survey_id}, {start_date}, {end_date})",
    ]

    if since is not None:
        conditions.append("timestamp >= {since}")
        placeholders["since"] = ast.Constant(value=since)
    if until is not None:
        conditions.append("timestamp <= {until}")
        placeholders["until"] = ast.Constant(value=until)

    if question_id:
        # Only return rows where this question has a non-empty answer.
        # coalesce-then-trim defends against NULL semantics in HogQL — without it the
        # equivalent `trim(...) != ''` predicate evaluates to NULL for nullified responses
        # and is silently ignored in some contexts.
        target_q = next(q for q in questions_in_scope if q["id"] == question_id)
        conditions.append(
            "length(trim(coalesce(getSurveyResponse({filter_q_idx}, {filter_q_id}), ''))) > 0",
        )
        placeholders["filter_q_idx"] = ast.Constant(value=target_q["index"])
        placeholders["filter_q_id"] = ast.Constant(value=target_q["id"])

        if score_lte is not None:
            conditions.append("toFloat(getSurveyResponse({filter_q_idx}, {filter_q_id})) <= {score_lte}")
            placeholders["score_lte"] = ast.Constant(value=score_lte)
        if score_gte is not None:
            conditions.append("toFloat(getSurveyResponse({filter_q_idx}, {filter_q_id})) >= {score_gte}")
            placeholders["score_gte"] = ast.Constant(value=score_gte)

    if exclude_uuids:
        conditions.append("uuid NOT IN {exclude_uuids}")
        placeholders["exclude_uuids"] = ast.Tuple(exprs=[ast.Constant(value=u) for u in exclude_uuids])

    query_str = f"""
        SELECT {select_clause}
        FROM events
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp DESC
    """

    select_ast = cast(ast.SelectQuery, parse_select(query_str, placeholders))
    paginator.execute_hogql_query(
        team=team,
        query_type="survey_responses_rows_query",
        query=select_ast,
    )

    # Column order matches the SELECT list above. The metadata columns slot in between
    # the fixed leading 3 (uuid, distinct_id, submitted_at) and the per-question answer columns.
    metadata_offset = 3  # uuid, distinct_id, submitted_at
    answer_offset = metadata_offset + len(_METADATA_COLUMNS)

    rows: list[SurveyResponseRow] = []
    for raw in paginator.results:
        uuid_val, distinct_id, submitted_at = raw[0], raw[1], raw[2]

        extra: dict[str, Any] = {}
        session_id: str | None = None
        for i, (alias, _) in enumerate(_METADATA_COLUMNS):
            value = raw[metadata_offset + i]
            if alias == "session_id":
                session_id = str(value) if value else None
            else:
                # Pass empty/null through as None to keep payloads clean for agents.
                extra[alias] = value if value not in (None, "") else None

        answers: list[QuestionAnswer] = []
        for i, q in enumerate(questions_in_scope):
            value = raw[answer_offset + i]
            if value in (None, ""):
                continue
            answers.append(
                QuestionAnswer(
                    question_id=q["id"],
                    question_index=q["index"],
                    question_text=q["text"],
                    question_type=q["type"],
                    answer=value,
                )
            )

        rows.append(
            SurveyResponseRow(
                uuid=str(uuid_val),
                distinct_id=str(distinct_id),
                session_id=session_id,
                submitted_at=submitted_at,
                answers=answers,
                extra=extra,
            )
        )

    return rows, paginator.has_more()
