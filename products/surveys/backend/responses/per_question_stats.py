"""Per-question response aggregation for the survey-stats endpoint."""

from dataclasses import dataclass, field
from datetime import datetime
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
    # Distribution: maps answer value (lowercased for choice/rating) to count.
    # Empty for open questions — distributions across free-text answers aren't meaningful;
    # use survey-responses-list with question_id + min_length to read the actual answers.
    distribution: dict[str, int] = field(default_factory=dict)
    # Numeric stats — only present for rating questions.
    average: float | None = None


def fetch_per_question_stats(
    *,
    survey: Survey,
    team: Team,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[PerQuestionStats]:
    """Aggregate response counts and distributions per survey question.

    Runs one HogQL query per question (typically <=10 questions per survey).
    For choice/rating questions distribution is by answer value;
    for open questions distribution is empty and callers should fall back to
    survey-responses-list to read the actual text.
    """
    questions = resolve_question_metadata(survey)
    if not questions:
        return []

    survey_id = str(survey.id)
    start_date = since or survey.start_date or survey.created_at
    end_date = until or survey.end_date or datetime.now()

    results: list[PerQuestionStats] = []
    for q in questions:
        question_id, question_index = q["id"], q["index"]
        question_type = q["type"]

        # Build the response key — prefer ID-keyed; fall back to index-keyed for legacy events.
        id_key = f"$survey_response_{question_id}" if question_id else None
        index_key = "$survey_response" if question_index == 0 else f"$survey_response_{question_index}"

        # COALESCE the two property keys so we count both ID- and index-keyed responses.
        # nullIf reduces empty strings to NULL so they're not counted as "answers".
        if id_key:
            response_expr = "coalesce(nullIf(properties.{id_key}, ''), nullIf(properties.{index_key}, ''))"
            placeholders: dict[str, ast.Expr] = {
                "survey_id": ast.Constant(value=survey_id),
                "start_date": ast.Constant(value=start_date),
                "end_date": ast.Constant(value=end_date),
                "id_key": ast.Constant(value=id_key),
                "index_key": ast.Constant(value=index_key),
            }
        else:
            response_expr = "nullIf(properties.{index_key}, '')"
            placeholders = {
                "survey_id": ast.Constant(value=survey_id),
                "start_date": ast.Constant(value=start_date),
                "end_date": ast.Constant(value=end_date),
                "index_key": ast.Constant(value=index_key),
            }

        # For open questions, just count the rows with non-empty answers — distribution is meaningless.
        if question_type == "open":
            query_str = f"""
                SELECT count() AS n
                FROM events
                WHERE event = 'survey sent'
                    AND properties.$survey_id = {{survey_id}}
                    AND timestamp >= {{start_date}}
                    AND timestamp <= {{end_date}}
                    AND uniqueSurveySubmissionsFilter({{survey_id}}, {{start_date}}, {{end_date}})
                    AND {response_expr} IS NOT NULL
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

        # For rating/choice: aggregate by answer value.
        query_str = f"""
            SELECT {response_expr} AS answer, count() AS n
            FROM events
            WHERE event = 'survey sent'
                AND properties.$survey_id = {{survey_id}}
                AND timestamp >= {{start_date}}
                AND timestamp <= {{end_date}}
                AND uniqueSurveySubmissionsFilter({{survey_id}}, {{start_date}}, {{end_date}})
                AND {response_expr} IS NOT NULL
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

        distribution: dict[str, int] = {}
        total_count = 0
        rating_sum = 0.0
        rating_count = 0
        for row in response.results:
            answer_raw, count_n = row[0], int(row[1])
            answer_str = str(answer_raw) if answer_raw is not None else ""
            if not answer_str:
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
