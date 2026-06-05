"""Per-question response aggregation for the survey-stats endpoint."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.surveys.backend.models import Survey
from products.surveys.backend.responses.fetch_rows import resolve_question_metadata


@dataclass(frozen=True)
class PerQuestionStats:
    question_id: str
    question_index: int
    question_text: str
    question_type: str
    response_count: int
    distribution: dict[str, int] = field(default_factory=dict)
    average: float | None = None


def fetch_per_question_stats(
    *,
    survey: Survey,
    team: Team,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[PerQuestionStats]:
    """Aggregate response counts and distributions per survey question.

    Runs one HogQL query per question (typically <=10 questions per survey),
    using the same `getSurveyResponse` helper the summarization fetch uses
    so question ID / index resolution matches the rest of the surveys API.
    For choice/rating questions distribution is by answer value;
    for open questions distribution is empty — callers should fall back to
    survey-responses-list to read the actual text.
    """
    questions = resolve_question_metadata(survey)
    if not questions:
        return []

    survey_id = str(survey.id)
    start_date = since or survey.start_date or survey.created_at
    end_date = until or survey.end_date or datetime.now(UTC)

    results: list[PerQuestionStats] = []
    for q in questions:
        question_id, question_index = q["id"], q["index"]
        question_type = q["type"]

        placeholders: dict[str, ast.Expr] = {
            "survey_id": ast.Constant(value=survey_id),
            "start_date": ast.Constant(value=start_date),
            "end_date": ast.Constant(value=end_date),
            "q_idx": ast.Constant(value=question_index),
            "q_id": ast.Constant(value=question_id),
        }

        # For open questions: just count non-empty responses — distribution across free-text
        # answers isn't meaningful and reading them is what survey-responses-list is for.
        #
        # Use coalesce(..., '') before trim so the count is correct when getSurveyResponse
        # resolves to NULL (e.g. via its nullIf path) — `NULL != ''` is NULL, which would
        # filter the row implicitly but doesn't always behave consistently in count contexts.
        if question_type == "open":
            query_str = """
                SELECT countIf(length(trim(coalesce(getSurveyResponse({q_idx}, {q_id}), ''))) > 0) AS n
                FROM events
                WHERE event = 'survey sent'
                    AND properties.`$survey_id` = {survey_id}
                    AND timestamp >= {start_date}
                    AND timestamp <= {end_date}
                    AND uniqueSurveySubmissionsFilter({survey_id}, {start_date}, {end_date})
            """
            select_ast = cast(ast.SelectQuery, parse_select(query_str, placeholders))
            response = execute_hogql_query(
                query=select_ast,
                team=team,
                query_type="survey_per_question_stats_open_query",
            )
            count_val = int(response.results[0][0]) if response.results else 0
            results.append(
                PerQuestionStats(
                    question_id=question_id,
                    question_index=question_index,
                    question_text=q["text"],
                    question_type=question_type,
                    response_count=count_val,
                )
            )
            continue

        # For rating/choice: aggregate by answer value to get a distribution.
        # Same defensive coalesce as the open branch — filter out NULL and empty before grouping.
        query_str = """
            SELECT getSurveyResponse({q_idx}, {q_id}) AS answer, count() AS n
            FROM events
            WHERE event = 'survey sent'
                AND properties.`$survey_id` = {survey_id}
                AND timestamp >= {start_date}
                AND timestamp <= {end_date}
                AND uniqueSurveySubmissionsFilter({survey_id}, {start_date}, {end_date})
                AND length(trim(coalesce(getSurveyResponse({q_idx}, {q_id}), ''))) > 0
            GROUP BY answer
            ORDER BY n DESC
            LIMIT 200
        """
        select_ast = cast(ast.SelectQuery, parse_select(query_str, placeholders))
        response = execute_hogql_query(
            query=select_ast,
            team=team,
            query_type="survey_per_question_stats_grouped_query",
        )

        # For choice questions, only the configured answer values are safe to expose under
        # `survey:read` — any value outside that set is user-entered free text (e.g. a
        # `hasOpenChoice` "Other: ___" response) and would leak respondent-entered content.
        # Bucket free-text answers under "<other>" so callers still see how many people picked
        # "Other" without exposing the text itself. Reading the text requires the responses
        # endpoint, which requires `query:read`.
        allowed_choices: set[str] | None = None
        if question_type in ("single_choice", "multiple_choice"):
            choices = q.get("choices") or []
            allowed_choices = set(choices) if choices else set()

        distribution: dict[str, int] = {}
        total_count = 0
        rating_sum = 0.0
        rating_count = 0
        other_count = 0
        for row in response.results:
            answer_raw, count_n = row[0], int(row[1])
            answer_str = str(answer_raw) if answer_raw is not None else ""
            if not answer_str:
                continue

            if allowed_choices is not None and answer_str not in allowed_choices:
                # Free-text "Other" — keep the count but not the value.
                other_count += count_n
                total_count += count_n
                continue

            distribution[answer_str] = count_n
            total_count += count_n
            if question_type == "rating":
                try:
                    rating_sum += float(answer_str) * count_n
                    rating_count += count_n
                except ValueError:
                    # Non-numeric rating answer — skip from avg, keep in distribution.
                    continue

        if other_count:
            distribution["<other>"] = other_count

        average = (rating_sum / rating_count) if rating_count else None

        results.append(
            PerQuestionStats(
                question_id=question_id,
                question_index=question_index,
                question_text=q["text"],
                question_type=question_type,
                response_count=total_count,
                distribution=distribution,
                average=average,
            )
        )

    return results
