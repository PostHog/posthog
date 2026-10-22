"""The bounded full-text search over a team's skills, and the excerpts it reports."""

import re
from collections.abc import Sequence
from typing import Any, Literal, Protocol, cast

from django.db import OperationalError
from django.db.models import Case, Exists, Expression, IntegerField, OuterRef, Q, QuerySet, Subquery, Value, When
from django.db.models.functions import Coalesce

import psycopg

from posthog.models import Team
from posthog.models.utils import execute_with_timeout

from products.access_control.backend.facade.user_access_control import UserAccessControl

from ..models.skills import LLMSkill, LLMSkillFile

SKILL_SEARCH_RESULT_LIMIT = 10
SKILL_SEARCH_MATCH_LIMIT = 2
SKILL_SEARCH_EXCERPT_LENGTH = 300
SKILL_SEARCH_TIMEOUT_MS = 5_000
SKILL_SEARCH_EXACT_NAME_BONUS = 5_000
SKILL_SEARCH_MAX_TOKENS = 8
SKILL_SEARCH_MIN_TOKEN_LENGTH = 2
SKILL_SEARCH_MIN_STEM_LENGTH = 5
SKILL_SEARCH_DERIVATIONAL_SUFFIXES = ("ations", "ation", "tions", "tion", "ings", "ing", "ed")
SKILL_SEARCH_SIBILANT_ES_ENDINGS = ("ches", "shes", "sses", "xes", "zes")
SkillSearchField = Literal["name", "description", "body", "path", "content"]
SKILL_SEARCH_FIELD_LOOKUPS: dict[SkillSearchField, str] = {
    "name": "name__icontains",
    "description": "description__icontains",
    "body": "body__icontains",
    "path": "path__icontains",
    "content": "content__icontains",
}


class _ScoredSkill(Protocol):
    search_score: int


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
                    "score": cast(_ScoredSkill, skill).search_score,
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
    tokens = _skill_search_tokens(query)
    matching_skill_files = skill_files.filter(
        _skill_search_field_query("path", query, tokens)
        | (markdown_file_query() & _skill_search_field_query("content", query, tokens))
    )
    file_path_score = Coalesce(
        Subquery(
            skill_files.annotate(score=_skill_search_field_score("path", query, tokens, 120))
            .order_by("-score")
            .values("score")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )
    file_content_score = Coalesce(
        Subquery(
            skill_files.filter(markdown_file_query())
            .annotate(score=_skill_search_field_score("content", query, tokens, 40))
            .order_by("-score")
            .values("score")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )

    queryset = LLMSkill.objects.filter(
        team=team,
        deleted=False,
        is_latest=True,
        category="",
    )
    queryset = user_access_control.filter_queryset_by_access_level(queryset, resource="llm_skill")
    queryset = queryset.filter(
        _skill_search_field_query("name", query, tokens)
        | _skill_search_field_query("description", query, tokens)
        | _skill_search_field_query("body", query, tokens)
        | Q(Exists(matching_skill_files))
    )

    exact_name_score = Case(
        When(name__iexact=query, then=Value(SKILL_SEARCH_EXACT_NAME_BONUS)),
        default=Value(0),
        output_field=IntegerField(),
    )
    score = (
        exact_name_score
        + _skill_search_field_score("name", query, tokens, 1_000)
        + _skill_search_field_score("description", query, tokens, 300)
        + _skill_search_field_score("body", query, tokens, 80)
        + file_path_score
        + file_content_score
    )
    return queryset.annotate(search_score=score).order_by("-search_score", "name", "id")[:SKILL_SEARCH_RESULT_LIMIT]


def search_matches(skill: LLMSkill, query: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    tokens = _skill_search_tokens(query)

    if _skill_search_match_term(skill.name, query, tokens) is not None:
        matches.append({"matched_field": "name", "excerpt": skill.name})
    description_match = _skill_search_match_term(skill.description, query, tokens)
    if description_match is not None:
        match_index = skill.description.lower().find(description_match.lower())
        excerpt_start = max(0, match_index - SKILL_SEARCH_EXCERPT_LENGTH // 2)
        matches.append(
            {
                "matched_field": "description",
                "excerpt": skill.description[excerpt_start : excerpt_start + SKILL_SEARCH_EXCERPT_LENGTH],
            }
        )
    body_match_term = _skill_search_match_term(skill.body, query, tokens)
    body_match = (
        _content_search_match(skill.body, body_match_term, matched_field="body", path="SKILL.md")
        if body_match_term is not None
        else None
    )
    if body_match is not None:
        matches.append(body_match)

    if len(matches) < SKILL_SEARCH_MATCH_LIMIT:
        remaining_match_count = SKILL_SEARCH_MATCH_LIMIT - len(matches)
        matching_paths = (
            skill.files.filter(_skill_search_field_query("path", query, tokens))
            .annotate(search_match_score=_skill_search_field_score("path", query, tokens, 120))
            .order_by("-search_match_score", "path")
            .values_list("path", flat=True)[:remaining_match_count]
        )
        for path in matching_paths:
            matches.append({"matched_field": "file_path", "path": path, "excerpt": path})

    if len(matches) < SKILL_SEARCH_MATCH_LIMIT:
        remaining_match_count = SKILL_SEARCH_MATCH_LIMIT - len(matches)
        file_content_query = Q(content__icontains=query)
        for variants in tokens:
            file_content_query |= _skill_search_variant_query("content", variants)
        content_files = (
            skill.files.filter(markdown_file_query(), file_content_query)
            .annotate(search_match_score=_skill_search_field_score("content", query, tokens, 40))
            .order_by("-search_match_score", "path")
            .values_list("path", "content")
        )[:remaining_match_count]
        for path, content in content_files:
            match_term = _skill_search_match_term(content, query, tokens)
            if match_term is None:
                continue
            match = _content_search_match(
                content,
                match_term,
                matched_field="file_content",
                path=path,
            )
            if match is not None:
                matches.append(match)

    return matches[:SKILL_SEARCH_MATCH_LIMIT]


def _skill_search_tokens(query: str) -> list[tuple[str, ...]]:
    raw_tokens = list(dict.fromkeys(re.findall(r"[^\W_]+", query.lower())))
    informative_tokens = [token for token in raw_tokens if len(token) >= SKILL_SEARCH_MIN_TOKEN_LENGTH]
    bounded_tokens = sorted(informative_tokens, key=len, reverse=True)[:SKILL_SEARCH_MAX_TOKENS] or raw_tokens[:1]
    return [_skill_search_variants(token) for token in bounded_tokens]


def _skill_search_variants(token: str) -> tuple[str, ...]:
    if len(token) < 6 or not token.isascii() or not token.isalpha():
        return (token,)

    stems: list[str] = []
    suffix = next(
        (
            candidate
            for candidate in SKILL_SEARCH_DERIVATIONAL_SUFFIXES
            if len(token) > len(candidate) and token.endswith(candidate)
        ),
        None,
    )
    if suffix is not None:
        stems.append(token[: -len(suffix)])
    elif token.endswith("ies"):
        stems.append(f"{token[:-3]}y")
    elif token.endswith(SKILL_SEARCH_SIBILANT_ES_ENDINGS):
        stems.append(token[:-2])
    elif token.endswith("es"):
        stems.extend((token[:-1], token[:-2]))
    elif token.endswith("s") and token != "status" and not token.endswith(("is", "ss")):
        stems.append(token[:-1])
    else:
        return (token,)

    variants = [token]
    for stem in stems:
        variants.append(stem)
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            variants.append(stem[:-1])
    return tuple(dict.fromkeys(variant for variant in variants if len(variant) >= SKILL_SEARCH_MIN_STEM_LENGTH))


def _skill_search_variant_query(field: SkillSearchField, variants: Sequence[str]) -> Q:
    lookup = SKILL_SEARCH_FIELD_LOOKUPS[field]
    query = Q()
    for variant in variants:
        query |= Q(**{lookup: variant})
    return query


def _skill_search_all_tokens_query(field: SkillSearchField, tokens: Sequence[Sequence[str]]) -> Q:
    query = Q()
    for variants in tokens:
        query &= _skill_search_variant_query(field, variants)
    return query


def _skill_search_any_token_query(field: SkillSearchField, tokens: Sequence[Sequence[str]]) -> Q:
    query = Q()
    for variants in tokens:
        query |= _skill_search_variant_query(field, variants)
    return query


def _skill_search_field_query(field: SkillSearchField, phrase: str, tokens: Sequence[Sequence[str]]) -> Q:
    return Q(**{SKILL_SEARCH_FIELD_LOOKUPS[field]: phrase}) | _skill_search_any_token_query(field, tokens)


def _skill_search_field_score(
    field: SkillSearchField, phrase: str, tokens: Sequence[Sequence[str]], weight: int
) -> Expression:
    phrase_score = Case(
        When(_skill_search_field_query(field, phrase, ()), then=Value(weight * 2)),
        default=Value(0),
        output_field=IntegerField(),
    )
    if not tokens:
        return phrase_score

    partial_weight = max(1, weight // len(tokens) // 4)
    partial_score: Expression = Value(0, output_field=IntegerField())
    for variants in tokens:
        partial_score += Case(
            When(_skill_search_variant_query(field, variants), then=Value(partial_weight)),
            default=Value(0),
            output_field=IntegerField(),
        )
    token_score = Case(
        When(_skill_search_all_tokens_query(field, tokens), then=Value(weight)),
        default=partial_score,
        output_field=IntegerField(),
    )
    return phrase_score + token_score


def _skill_search_match_term(content: str, phrase: str, tokens: Sequence[Sequence[str]]) -> str | None:
    lowered = content.lower()
    if phrase.lower() in lowered:
        return phrase
    return next((variant for variants in tokens for variant in variants if variant in lowered), None)


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
