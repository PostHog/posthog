"""Per-question response aggregation for the survey-stats endpoint."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.models import Team

from products.surveys.backend.models import Survey
from products.surveys.backend.responses.fetch_rows import (
    RESPONSE_EVENT_FILTER,
    SUBMISSION_GROUPING_KEY,
    resolve_question_metadata,
)

OTHER_BUCKET = "<other>"


@dataclass(frozen=True)
class PerQuestionStats:
    question_id: str
    question_index: int
    question_text: str
    question_type: str
    response_count: int
    distribution: dict[str, int] = field(default_factory=dict)
    average: float | None = None


# A multiple-choice answer arrives in one of these shapes:
# - a native JSON array property, which only the array form of getSurveyResponse reads;
# - a string that holds a JSON array, such as '["a","b"]', which only the string form reads;
# - a plain string with one choice.
_MULTIPLE_CHOICE_ANSWER_JSON = """
    if(
        length(getSurveyResponse({q_idx}, {q_id}, true)) > 0,
        concat('[', arrayStringConcat(getSurveyResponse({q_idx}, {q_id}, true), ','), ']'),
        trim(coalesce(getSurveyResponse({q_idx}, {q_id}), ''))
    )
"""


def _fetch_multiple_choice_stats(
    *,
    question: dict[str, Any],
    team: Team,
    placeholders: dict[str, ast.Expr],
) -> PerQuestionStats:
    """Count each choice once per submission, and bucket every unknown value as "<other>".

    The query maps values to their base choice inside ClickHouse, so free text never leaves it.
    A submission counts once in `response_count`, also when it selects several choices.
    """
    choice_map: dict[str, str] = question.get("choice_map") or {}
    # transform() needs non-empty arrays. Picks are never blank, so the blank key never matches.
    choice_keys = list(choice_map) or [""]
    choice_values = list(choice_map.values()) or [OTHER_BUCKET]

    query_str = """
        SELECT count() AS submissions, sumMap(picks, arrayMap(x -> 1, picks)) AS pick_counts
        FROM (
            SELECT arrayDistinct(arrayMap(x -> transform(x, {choice_keys}, {choice_values}, {other}), answer)) AS picks
            FROM (
                SELECT argMaxIf(response, timestamp, length(response) > 0) AS answer
                FROM (
                    SELECT
                        {answer_json} AS answer_json,
                        arrayFilter(
                            x -> length(trim(x)) > 0,
                            if(startsWith(answer_json, '['), JSONExtract(answer_json, 'Array(String)'), [answer_json])
                        ) AS response,
                        timestamp,
                        {grouping_key} AS submission_key
                    FROM events
                    WHERE {response_events}
                        AND properties.`$survey_id` = {survey_id}
                        AND timestamp >= {start_date}
                        AND timestamp <= {end_date}
                )
                GROUP BY submission_key
                HAVING length(answer) > 0
            )
        )
    """
    select_ast = cast(
        ast.SelectQuery,
        parse_select(
            query_str,
            {
                **placeholders,
                "answer_json": parse_expr(_MULTIPLE_CHOICE_ANSWER_JSON, placeholders),
                "choice_keys": ast.Array(exprs=[ast.Constant(value=key) for key in choice_keys]),
                "choice_values": ast.Array(exprs=[ast.Constant(value=value) for value in choice_values]),
                "other": ast.Constant(value=OTHER_BUCKET),
            },
        ),
    )
    response = execute_hogql_query(
        query=select_ast,
        team=team,
        query_type="survey_per_question_stats_multiple_choice_query",
    )

    submissions = 0
    distribution: dict[str, int] = {}
    if response.results:
        submissions = int(response.results[0][0])
        keys, counts = response.results[0][1]
        distribution = {str(key): int(count) for key, count in sorted(zip(keys, counts), key=lambda kv: -kv[1])}
        if OTHER_BUCKET in distribution:
            distribution[OTHER_BUCKET] = distribution.pop(OTHER_BUCKET)

    return PerQuestionStats(
        question_id=question["id"],
        question_index=question["index"],
        question_text=question["text"],
        question_type=question["type"],
        response_count=submissions,
        distribution=distribution,
    )


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
            "grouping_key": parse_expr(SUBMISSION_GROUPING_KEY),
            "response_events": parse_expr(RESPONSE_EVENT_FILTER),
        }

        # For open questions: just count non-empty responses — distribution across free-text
        # answers isn't meaningful and reading them is what survey-responses-list is for.
        #
        # Use coalesce(..., '') before trim so the count is correct when getSurveyResponse
        # resolves to NULL (e.g. via its nullIf path) — `NULL != ''` is NULL, which would
        # filter the row implicitly but doesn't always behave consistently in count contexts.
        if question_type == "open":
            # Merge each submission's events into one answer (latest non-null), then count
            # the submissions that ended up with a non-empty answer.
            query_str = """
                SELECT countIf(length(trim(coalesce(answer, ''))) > 0) AS n
                FROM (
                    SELECT argMaxIf(response, timestamp, isNotNull(response)) AS answer
                    FROM (
                        SELECT
                            getSurveyResponse({q_idx}, {q_id}) AS response,
                            timestamp,
                            {grouping_key} AS submission_key
                        FROM events
                        WHERE {response_events}
                            AND properties.`$survey_id` = {survey_id}
                            AND timestamp >= {start_date}
                            AND timestamp <= {end_date}
                    )
                    GROUP BY submission_key
                )
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

        if question_type == "multiple_choice":
            results.append(_fetch_multiple_choice_stats(question=q, team=team, placeholders=placeholders))
            continue

        # For rating/choice: aggregate by answer value to get a distribution.
        # Same defensive coalesce as the open branch — filter out NULL and empty before grouping.
        # Merge each submission's events into one answer (latest non-null), then build the
        # distribution across those merged answers.
        query_str = """
            SELECT answer, count() AS n
            FROM (
                SELECT argMaxIf(response, timestamp, isNotNull(response)) AS answer
                FROM (
                    SELECT
                        getSurveyResponse({q_idx}, {q_id}) AS response,
                        timestamp,
                        {grouping_key} AS submission_key
                    FROM events
                    WHERE {response_events}
                        AND properties.`$survey_id` = {survey_id}
                        AND timestamp >= {start_date}
                        AND timestamp <= {end_date}
                )
                GROUP BY submission_key
                HAVING length(trim(coalesce(answer, ''))) > 0
            )
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
        # endpoint, which requires `query:read`. Translated answers map back to their base
        # choice so they aggregate with it rather than being redacted into "<other>".
        choice_map: dict[str, str] | None = None
        if question_type == "single_choice":
            choice_map = q.get("choice_map") or {}

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

            if choice_map is not None:
                normalized = choice_map.get(answer_str)
                if normalized is None:
                    # Free-text "Other" — keep the count but not the value.
                    other_count += count_n
                    total_count += count_n
                    continue
                answer_str = normalized

            distribution[answer_str] = distribution.get(answer_str, 0) + count_n
            total_count += count_n
            if question_type == "rating":
                try:
                    rating_sum += float(answer_str) * count_n
                    rating_count += count_n
                except ValueError:
                    # Non-numeric rating answer — skip from avg, keep in distribution.
                    continue

        if other_count:
            distribution[OTHER_BUCKET] = other_count

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
