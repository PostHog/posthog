"""Survey responses linked to another product's record through an event property, such as `$ai_trace_id`.

Responses merge per submission like the responses API in `fetch_rows`: the same response events, grouped by
`SUBMISSION_GROUPING_KEY`, each question keeping its latest non-empty answer, archived responses left out. This read
also returns every picked choice of a multiple choice question, maps translated choices back to the base language,
matches survey ids however their case is written, and says whether each submission was completed.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from django.db.models import QuerySet

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.surveys.backend.models import Survey
from products.surveys.backend.responses.fetch_rows import (
    RESPONSE_EVENT_FILTER,
    SUBMISSION_GROUPING_KEY,
    resolve_question_metadata,
)
from products.surveys.backend.util import get_archived_response_uuids

LINKED_SURVEYS_LIMIT = 10
# Per survey, newest first.
LINKED_SUBMISSIONS_LIMIT = 100
_CHOICE_TYPES = ("single_choice", "multiple_choice")


@frozen
class SurveyRef:
    id: str
    # None when no survey of the team has this id.
    name: str | None


@frozen
class RatingScale:
    scale: int | None
    display: str | None
    lower_bound_label: str | None
    upper_bound_label: str | None


@frozen
class LinkedSurveyAnswer:
    question_id: str
    question_index: int
    question_text: str
    question_type: str
    # Set for rating questions only.
    rating: RatingScale | None
    # Every picked choice for a multiple choice question, the answer as text otherwise.
    value: str | tuple[str, ...]


LinkedResponseUnavailable = Literal["survey_not_found", "no_questions"]


@frozen
class LinkedSurveyResponse:
    survey: SurveyRef
    submission_id: str
    submitted_at: datetime
    complete: bool
    answers: tuple[LinkedSurveyAnswer, ...]
    # Why the answers cannot be read, when they cannot.
    unavailable: LinkedResponseUnavailable | None


@frozen
class UnansweredSurvey:
    survey: SurveyRef
    shown_at: datetime


@frozen
class LinkedSurveyResponses:
    responses: tuple[LinkedSurveyResponse, ...]
    unanswered: tuple[UnansweredSurvey, ...]


@frozen
class _SurveyActivity:
    survey_id: str
    raw_ids: tuple[str, ...]
    responses: int
    first_shown_at: datetime | None


@frozen
class _Link:
    property_name: str
    property_value: str
    since: datetime
    until: datetime | None

    def condition(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", self.property_name]),
                right=ast.Constant(value=self.property_value),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["timestamp"]),
                right=ast.Constant(value=self.since),
            ),
        ]
        if self.until is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=self.until),
                )
            )
        return ast.And(exprs=exprs)


def _canonical_uuid(value: str) -> str | None:
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _execute(team: Team, user: User | None, name: str, query: ast.SelectQuery) -> list[Sequence[Any]]:
    with tags_context(product=Product.SURVEYS):
        tag_queries(name=name)
        response = execute_hogql_query(query=query, team=team, user=user, query_type=name, workload=Workload.ONLINE)
    return list(response.results or [])


def _read_activity(team: Team, user: User | None, link: _Link) -> list[_SurveyActivity]:
    query = cast(
        ast.SelectQuery,
        parse_select(
            f"""
            SELECT
                properties.`$survey_id` AS raw_survey_id,
                countIf({RESPONSE_EVENT_FILTER}) AS responses,
                countIf(event = 'survey shown') AS shown,
                minIf(timestamp, event = 'survey shown') AS first_shown_at
            FROM events
            WHERE (event = 'survey shown' OR {RESPONSE_EVENT_FILTER}) AND {{link}}
            GROUP BY raw_survey_id
            ORDER BY min(timestamp)
            LIMIT {{limit}}
            """,
            {"link": link.condition(), "limit": ast.Constant(value=LINKED_SURVEYS_LIMIT)},
        ),
    )
    # Survey ids are UUIDs that some SDKs write in upper case, so each survey gathers every spelling of its id.
    grouped: dict[str, _SurveyActivity] = {}
    for raw_id, responses, shown, first_shown_at in _execute(team, user, "survey_linked_activity", query):
        if not raw_id:
            continue
        survey_id = _canonical_uuid(raw_id) or raw_id
        seen = grouped.get(survey_id)
        shown_at = first_shown_at if shown else None
        if seen is None:
            grouped[survey_id] = _SurveyActivity(
                survey_id=survey_id, raw_ids=(raw_id,), responses=responses, first_shown_at=shown_at
            )
        else:
            grouped[survey_id] = _SurveyActivity(
                survey_id=survey_id,
                raw_ids=(*seen.raw_ids, raw_id),
                responses=seen.responses + responses,
                first_shown_at=min(filter(None, (seen.first_shown_at, shown_at)), default=None),
            )
    return list(grouped.values())


@frozen
class _SurveyAccess:
    readable: dict[str, Survey]
    # Surveys the team has but the viewer may not read.
    hidden: set[str]


def _survey_access(team: Team, user: User | None, survey_ids: Sequence[str]) -> _SurveyAccess:
    uuids = [survey_id for survey_id in survey_ids if _canonical_uuid(survey_id)]
    surveys: QuerySet[Survey] = Survey.objects.filter(team_id=team.pk, id__in=uuids)
    existing = {str(survey_id) for survey_id in surveys.values_list("id", flat=True)}
    if user is not None:
        surveys = UserAccessControl(user=user, team=team).filter_queryset_by_access_level(surveys, resource="survey")
    readable = {str(survey.id): survey for survey in surveys}
    return _SurveyAccess(readable=readable, hidden=existing - readable.keys())


def _submissions_query(
    activity: _SurveyActivity, link: _Link, questions: list[dict[str, Any]], archived: set[str]
) -> ast.SelectQuery:
    placeholders: dict[str, ast.Expr] = {
        "link": link.condition(),
        "survey_ids": ast.Tuple(exprs=[ast.Constant(value=raw_id) for raw_id in activity.raw_ids]),
        "grouping_key": parse_expr(SUBMISSION_GROUPING_KEY),
        "limit": ast.Constant(value=LINKED_SUBMISSIONS_LIMIT),
    }
    inner_answers: list[str] = []
    outer_answers: list[str] = []
    for question in questions:
        index = question["index"]
        is_multiple_choice = question["type"] == "multiple_choice"
        placeholders[f"q_idx_{index}"] = ast.Constant(value=index)
        placeholders[f"q_id_{index}"] = ast.Constant(value=question["id"])
        placeholders[f"q_mc_{index}"] = ast.Constant(value=is_multiple_choice)
        inner_answers.append(f"getSurveyResponse({{q_idx_{index}}}, {{q_id_{index}}}, {{q_mc_{index}}}) AS raw_{index}")
        present = f"notEmpty(raw_{index})" if is_multiple_choice else f"isNotNull(raw_{index})"
        outer_answers.append(f"argMaxIf(raw_{index}, timestamp, {present}) AS answer_{index}")
    having = ""
    if archived:
        # Archiving records the submission's latest uuid, which is what argMax(uuid) returns.
        having = "HAVING uuid NOT IN {archived}"
        placeholders["archived"] = ast.Tuple(exprs=[ast.Constant(value=uuid) for uuid in archived])
    return cast(
        ast.SelectQuery,
        parse_select(
            f"""
            SELECT
                submission_key,
                argMax(uuid, timestamp) AS uuid,
                max(timestamp) AS submitted_at,
                countIf(event = 'survey sent' AND completed NOT IN ('false', '0')) > 0 AS complete
                {"".join(f", {column}" for column in outer_answers)}
            FROM (
                SELECT
                    uuid,
                    event,
                    timestamp,
                    {{grouping_key}} AS submission_key,
                    coalesce(toString(properties.`$survey_completed`), '') AS completed
                    {"".join(f", {column}" for column in inner_answers)}
                FROM events
                WHERE {RESPONSE_EVENT_FILTER} AND properties.`$survey_id` IN {{survey_ids}} AND {{link}}
            )
            GROUP BY submission_key
            {having}
            ORDER BY submitted_at DESC
            LIMIT {{limit}}
            """,
            placeholders,
        ),
    )


def _rating_scale(question: dict[str, Any]) -> RatingScale:
    scale = question.get("scale")
    return RatingScale(
        scale=scale if isinstance(scale, int) else None,
        display=question.get("display"),
        lower_bound_label=question.get("lowerBoundLabel"),
        upper_bound_label=question.get("upperBoundLabel"),
    )


def _answer_value(raw: Any, question: dict[str, Any]) -> str | tuple[str, ...] | None:
    # Answers to a translated survey arrive in the respondent's language, so choices map back to the base language.
    choice_map: dict[str, str] = question["choice_map"] if question["type"] in _CHOICE_TYPES else {}
    if question["type"] == "multiple_choice":
        choices = tuple(str(choice) for choice in (json.loads(item) for item in raw or []) if choice not in (None, ""))
        return tuple(choice_map.get(choice, choice) for choice in choices) or None
    if raw in (None, ""):
        return None
    return choice_map.get(str(raw), str(raw))


def _answers(values: Sequence[Any], questions: list[dict[str, Any]], survey: Survey) -> tuple[LinkedSurveyAnswer, ...]:
    raw_questions = survey.questions or []
    answers: list[LinkedSurveyAnswer] = []
    for question, raw in zip(questions, values, strict=True):
        value = _answer_value(raw, question)
        if value is None:
            continue
        answers.append(
            LinkedSurveyAnswer(
                question_id=question["id"],
                question_index=question["index"],
                question_text=question["text"],
                question_type=question["type"],
                rating=_rating_scale(raw_questions[question["index"]]) if question["type"] == "rating" else None,
                value=value,
            )
        )
    return tuple(answers)


def _read_responses(
    team: Team, user: User | None, link: _Link, activity: _SurveyActivity, survey: Survey | None
) -> list[LinkedSurveyResponse]:
    questions = resolve_question_metadata(survey) if survey is not None else []
    unavailable: LinkedResponseUnavailable | None = (
        "survey_not_found" if survey is None else "no_questions" if not questions else None
    )
    archived = get_archived_response_uuids(survey.id, team.pk) if survey is not None else set()
    ref = SurveyRef(id=activity.survey_id, name=survey.name if survey is not None else None)
    rows = _execute(team, user, "survey_linked_responses", _submissions_query(activity, link, questions, archived))
    return [
        LinkedSurveyResponse(
            survey=ref,
            submission_id=str(submission_key),
            submitted_at=submitted_at,
            complete=bool(complete),
            answers=_answers(values, questions, survey) if survey is not None else (),
            unavailable=unavailable,
        )
        for submission_key, _uuid, submitted_at, complete, *values in rows
    ]


def get_survey_responses_linked_to(
    team: Team,
    user: User | None,
    *,
    property_name: str,
    property_value: str,
    since: datetime,
    until: datetime | None = None,
) -> LinkedSurveyResponses:
    """Responses whose events carry `property_name = property_value`, merged per submission as the responses API
    merges them, with each question's text and type, oldest first. Also the surveys shown with no response.

    A response to a survey the team no longer has is kept, marked unavailable. Surveys the user cannot read are left
    out. Reads at most `LINKED_SURVEYS_LIMIT` surveys and `LINKED_SUBMISSIONS_LIMIT` submissions per survey."""
    link = _Link(property_name=property_name, property_value=property_value, since=since, until=until)
    activities = _read_activity(team, user, link)
    access = _survey_access(team, user, [activity.survey_id for activity in activities])
    responses: list[LinkedSurveyResponse] = []
    unanswered: list[UnansweredSurvey] = []
    for activity in activities:
        if activity.survey_id in access.hidden:
            continue
        survey = access.readable.get(activity.survey_id)
        if activity.responses:
            responses.extend(_read_responses(team, user, link, activity, survey))
        elif activity.first_shown_at is not None:
            ref = SurveyRef(id=activity.survey_id, name=survey.name if survey is not None else None)
            unanswered.append(UnansweredSurvey(survey=ref, shown_at=activity.first_shown_at))
    return LinkedSurveyResponses(
        responses=tuple(sorted(responses, key=lambda response: response.submitted_at)),
        unanswered=tuple(sorted(unanswered, key=lambda survey: survey.shown_at)),
    )
