"""The bounded full-text search over a team's skills, and the excerpts it reports."""

from typing import Any

from django.db import OperationalError
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, QuerySet, Value, When

import psycopg

from posthog.models import Team
from posthog.models.utils import execute_with_timeout

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..models.skills import LLMSkill, LLMSkillFile

SKILL_SEARCH_RESULT_LIMIT = 10
SKILL_SEARCH_MATCH_LIMIT = 2
SKILL_SEARCH_EXCERPT_LENGTH = 300
SKILL_SEARCH_TIMEOUT_MS = 5_000


class SkillSearchTimeout(Exception):
    """The search exceeded SKILL_SEARCH_TIMEOUT_MS in the database."""


def search_skills(team: Team, user_access_control: UserAccessControl, query: str) -> list[dict[str, Any]]:
    """Every readable skill matching the query, best match first, with excerpts.

    Raises SkillSearchTimeout when the query outruns its database timeout. The search spans skill
    bodies and bundled file contents, so a broad query on a large team can reach it.
    """
    try:
        with execute_with_timeout(SKILL_SEARCH_TIMEOUT_MS):
            return [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "matches": search_matches(skill, query),
                }
                for skill in search_queryset(team, user_access_control, query)
            ]
    except OperationalError as err:
        if not isinstance(err.__cause__, psycopg.errors.QueryCanceled):
            raise
        raise SkillSearchTimeout from err


def search_queryset(team: Team, user_access_control: UserAccessControl, query: str) -> QuerySet[LLMSkill]:
    skill_files = LLMSkillFile.objects.filter(skill_id=OuterRef("pk"))
    queryset = LLMSkill.objects.filter(
        team=team,
        deleted=False,
        is_latest=True,
        category="",
    ).annotate(
        search_file_path_match=Exists(skill_files.filter(path__icontains=query)),
        search_file_content_match=Exists(skill_files.filter(markdown_file_query(), content__icontains=query)),
    )
    queryset = user_access_control.filter_queryset_by_access_level(queryset, resource="llm_skill")
    return (
        queryset.filter(
            Q(name__icontains=query)
            | Q(description__icontains=query)
            | Q(body__icontains=query)
            | Q(search_file_path_match=True)
            | Q(search_file_content_match=True)
        )
        .annotate(
            search_rank=Case(
                When(name__iexact=query, then=Value(0)),
                When(name__icontains=query, then=Value(1)),
                When(description__icontains=query, then=Value(2)),
                When(body__icontains=query, then=Value(3)),
                When(search_file_path_match=True, then=Value(4)),
                When(search_file_content_match=True, then=Value(5)),
                default=Value(6),
                output_field=IntegerField(),
            )
        )
        .order_by("search_rank", "name", "id")[:SKILL_SEARCH_RESULT_LIMIT]
    )


def search_matches(skill: LLMSkill, query: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    lowered_query = query.lower()

    if lowered_query in skill.name.lower():
        matches.append({"matched_field": "name", "excerpt": skill.name})
    if lowered_query in skill.description.lower():
        match_index = skill.description.lower().find(lowered_query)
        excerpt_start = max(0, match_index - SKILL_SEARCH_EXCERPT_LENGTH // 2)
        matches.append(
            {
                "matched_field": "description",
                "excerpt": skill.description[excerpt_start : excerpt_start + SKILL_SEARCH_EXCERPT_LENGTH],
            }
        )
    body_match = _content_search_match(skill.body, query, matched_field="body", path="SKILL.md")
    if body_match is not None:
        matches.append(body_match)

    if len(matches) < SKILL_SEARCH_MATCH_LIMIT:
        remaining_match_count = SKILL_SEARCH_MATCH_LIMIT - len(matches)
        matching_paths = (
            skill.files.filter(path__icontains=query)
            .order_by("path")
            .values_list("path", flat=True)[:remaining_match_count]
        )
        for path in matching_paths:
            matches.append({"matched_field": "file_path", "path": path, "excerpt": path})

    if len(matches) < SKILL_SEARCH_MATCH_LIMIT:
        remaining_match_count = SKILL_SEARCH_MATCH_LIMIT - len(matches)
        content_files = (
            skill.files.filter(markdown_file_query(), content__icontains=query)
            .order_by("path")
            .values_list("path", "content")
        )[:remaining_match_count]
        for path, content in content_files:
            match = _content_search_match(
                content,
                query,
                matched_field="file_content",
                path=path,
            )
            if match is not None:
                matches.append(match)

    return matches[:SKILL_SEARCH_MATCH_LIMIT]


def _content_search_match(content: str, query: str, *, matched_field: str, path: str) -> dict[str, Any] | None:
    match_index = content.lower().find(query.lower())
    if match_index == -1:
        return None

    line = content.count("\n", 0, match_index) + 1
    line_start = content.rfind("\n", 0, match_index) + 1
    line_end = content.find("\n", match_index)
    if line_end == -1:
        line_end = len(content)
    line_content = content[line_start:line_end].strip()
    excerpt_source = line_content or content
    excerpt_match_index = excerpt_source.lower().find(query.lower())
    excerpt_start = max(0, excerpt_match_index - SKILL_SEARCH_EXCERPT_LENGTH // 2)
    excerpt = excerpt_source[excerpt_start : excerpt_start + SKILL_SEARCH_EXCERPT_LENGTH]
    return {
        "matched_field": matched_field,
        "path": path,
        "line": line,
        "excerpt": excerpt[:SKILL_SEARCH_EXCERPT_LENGTH],
    }


def markdown_file_query() -> Q:
    return Q(path__iendswith=".md") | Q(content_type__icontains="markdown")
