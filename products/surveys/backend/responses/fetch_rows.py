"""Fetch full survey response rows (with metadata) for the responses API.

The summarization fetch helper returns response strings only — sufficient for LLM
input but not for agents that need to cross-pivot to recordings, events, or persons.
This module returns rows with `distinct_id`, `session_id`, `submitted_at`, resolved
per-question answers, and optional person properties.
"""

from dataclasses import dataclass, field
from datetime import datetime
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
    person_properties: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def resolve_question_metadata(survey: Survey) -> list[dict[str, Any]]:
    """Return survey questions with stable `(id, index, text, type, choices)` shape.

    Survey questions are stored as a free-form JSON array. This helper hides that
    detail from callers and guarantees the keys we depend on are present.
    """
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


def _extract_answer(properties: dict[str, Any], question_id: str, question_index: int) -> Any:
    """Resolve the answer for a question from a survey-sent event's properties payload.

    Mirrors the canonical lookup priority used elsewhere in the codebase:
    `$survey_response_<id>` is preferred (stable across question edits);
    `$survey_response_<index>` is the fallback (legacy events);
    `$survey_response` is the legacy fallback for index 0.
    """
    by_id_key = f"$survey_response_{question_id}" if question_id else None
    if by_id_key and by_id_key in properties:
        value = properties[by_id_key]
        if value not in (None, ""):
            return value

    if question_index == 0:
        legacy_value = properties.get("$survey_response")
        if legacy_value not in (None, ""):
            return legacy_value

    indexed_key = f"$survey_response_{question_index}"
    indexed_value = properties.get(indexed_key)
    if indexed_value not in (None, ""):
        return indexed_value

    return None


def fetch_response_rows(
    *,
    survey: Survey,
    team: Team,
    since: datetime | None = None,
    until: datetime | None = None,
    question_id: str | None = None,
    score_lte: float | None = None,
    score_gte: float | None = None,
    include_person_properties: bool = False,
    limit: int = 100,
    offset: int = 0,
    exclude_uuids: set[str] | None = None,
) -> tuple[list[SurveyResponseRow], bool]:
    """Fetch survey response rows for the responses API.

    `score_lte` / `score_gte` require `question_id` — the score filter is only
    meaningful against a specific rating question. Without it the semantics
    (which rating? across questions OR?) become ambiguous; we deliberately
    reject that combination at the caller level.
    """
    if (score_lte is not None or score_gte is not None) and not question_id:
        raise ValueError("score_lte / score_gte require question_id")

    survey_id = str(survey.id)
    questions = resolve_question_metadata(survey)

    if question_id and not any(q["id"] == question_id for q in questions):
        return [], False

    paginator = HogQLHasMorePaginator(limit=limit, offset=offset)

    select_columns = [
        "uuid",
        "distinct_id",
        "properties.$session_id AS session_id",
        "timestamp AS submitted_at",
        "properties AS event_properties",
    ]
    if include_person_properties:
        select_columns.append("person.properties AS person_props")

    conditions = [
        "event = 'survey sent'",
        "properties.$survey_id = {survey_id}",
        "uniqueSurveySubmissionsFilter({survey_id}, {start_date}, {end_date})",
    ]
    placeholders: dict[str, ast.Expr] = {
        "survey_id": ast.Constant(value=survey_id),
        # uniqueSurveySubmissionsFilter requires bounded dates — fall back to
        # the survey lifetime when the caller didn't supply explicit bounds.
        "start_date": ast.Constant(value=since or survey.start_date or survey.created_at),
        "end_date": ast.Constant(value=until or survey.end_date or datetime.now()),
    }

    if since is not None:
        conditions.append("timestamp >= {since}")
        placeholders["since"] = ast.Constant(value=since)
    if until is not None:
        conditions.append("timestamp <= {until}")
        placeholders["until"] = ast.Constant(value=until)

    if question_id:
        # Require the targeted question to have a non-empty answer.
        # We don't filter by index-keyed fallbacks here because callers asking
        # for a specific question_id explicitly care about ID-keyed responses.
        conditions.append("trim(properties.{response_key}) != ''")
        placeholders["response_key"] = ast.Constant(value=f"$survey_response_{question_id}")

    if score_lte is not None:
        conditions.append("toFloat(properties.{response_key}) <= {score_lte}")
        placeholders["score_lte"] = ast.Constant(value=score_lte)
    if score_gte is not None:
        conditions.append("toFloat(properties.{response_key}) >= {score_gte}")
        placeholders["score_gte"] = ast.Constant(value=score_gte)

    if exclude_uuids:
        conditions.append("uuid NOT IN {exclude_uuids}")
        placeholders["exclude_uuids"] = ast.Tuple(exprs=[ast.Constant(value=u) for u in exclude_uuids])

    query_str = f"""
        SELECT {", ".join(select_columns)}
        FROM events
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp DESC
    """

    select_ast = cast(ast.SelectQuery, parse_select(query_str, placeholders))
    query_response = paginator.execute_hogql_query(
        team=team,
        query_type="survey_responses_rows_query",
        query=select_ast,
    )

    rows: list[SurveyResponseRow] = []
    for raw in query_response.results:
        uuid_val, distinct_id, session_id, submitted_at, event_properties = raw[:5]
        person_props = raw[5] if include_person_properties and len(raw) > 5 else None

        properties_dict: dict[str, Any] = event_properties if isinstance(event_properties, dict) else {}

        answers: list[QuestionAnswer] = []
        for question in questions:
            if question_id and question["id"] != question_id:
                continue
            value = _extract_answer(properties_dict, question["id"], question["index"])
            if value is None:
                continue
            answers.append(
                QuestionAnswer(
                    question_id=question["id"],
                    question_index=question["index"],
                    question_text=question["text"],
                    question_type=question["type"],
                    answer=value,
                )
            )

        extra = {
            "device_type": properties_dict.get("$device_type"),
            "browser": properties_dict.get("$browser"),
            "os": properties_dict.get("$os"),
            "geoip_country_code": properties_dict.get("$geoip_country_code"),
            "geoip_country_name": properties_dict.get("$geoip_country_name"),
            "geoip_city_name": properties_dict.get("$geoip_city_name"),
            "current_url": properties_dict.get("$current_url"),
            "iteration": properties_dict.get("$survey_iteration"),
        }

        rows.append(
            SurveyResponseRow(
                uuid=str(uuid_val),
                distinct_id=str(distinct_id),
                session_id=str(session_id) if session_id else None,
                submitted_at=submitted_at,
                answers=answers,
                person_properties=person_props if isinstance(person_props, dict) else None,
                extra=extra,
            )
        )

    return rows, paginator.has_more()
