import json
import dataclasses
from typing import Any

from django.conf import settings

import re2
import structlog

from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.llm.gateway_client import get_llm_client
from posthog.models import Team

from products.web_analytics.backend.path_cleaning_suggestions.prompts import (
    SYSTEM_PROMPT,
    SuggestedRule,
    SuggestedRulesResponse,
    build_user_prompt,
)

logger = structlog.get_logger(__name__)

DEFAULT_SAMPLE_DAYS = 30
DEFAULT_SAMPLE_LIMIT = 300
DEFAULT_MIN_DISTINCT_PATHS = 50
MAX_EXAMPLES_PER_RULE = 3


@dataclasses.dataclass
class AnnotatedRule:
    regex: str
    alias: str
    order: int
    reason: str
    match_count: int
    # Real sampled paths; kept in memory for the management command's printout but never
    # stored in the health-issue payload (see build_suggestion_payload).
    examples: list[dict[str, str]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class TeamSuggestionResult:
    # status: generated | skipped_inactive | skipped_configured | skipped_low_cardinality
    #         | skipped_no_paths | error
    team_id: int
    status: str
    rules: list[AnnotatedRule]
    sampled_path_count: int
    distinct_path_count: int
    existing_rule_count: int
    model: str = ""
    error: str | None = None


DEFAULT_VISITED_WITHIN_DAYS = 30


def _resolve_model() -> str:
    return getattr(settings, "WEB_ANALYTICS_PATH_CLEANING_SUGGESTIONS_MODEL", "claude-haiku-4-5")


def has_recent_pageviews(team: Team, *, days: int) -> bool:
    """True if the team sent any `$pageview` within the window — a cheap proxy for "actively using
    web analytics". `LIMIT 1` lets ClickHouse early-terminate instead of counting the full window."""
    query = f"""
        SELECT 1
        FROM events
        WHERE event = '$pageview'
          AND timestamp >= now() - toIntervalDay({int(days)})
        LIMIT 1
    """
    response = execute_hogql_query(query=query, team=team, query_type="web_path_cleaning_recent_pageviews")
    return bool(response.results)


def sample_pathnames(team: Team, *, days: int, limit: int) -> list[tuple[str, int]]:
    # days/limit are internal ints (settings / argparse), safe to inline — not user input.
    query = f"""
        SELECT properties.$pathname AS path, count() AS views
        FROM events
        WHERE event = '$pageview'
          AND timestamp >= now() - toIntervalDay({int(days)})
          AND properties.$pathname IS NOT NULL
          AND properties.$pathname != ''
        GROUP BY path
        ORDER BY views DESC
        LIMIT {int(limit)}
    """
    response = execute_hogql_query(query=query, team=team, query_type="web_path_cleaning_sample")
    return [(str(row[0]), int(row[1])) for row in response.results or []]


def count_distinct_pathnames(team: Team, *, days: int) -> int:
    query = f"""
        SELECT count(DISTINCT properties.$pathname)
        FROM events
        WHERE event = '$pageview'
          AND timestamp >= now() - toIntervalDay({int(days)})
          AND properties.$pathname IS NOT NULL
          AND properties.$pathname != ''
    """
    response = execute_hogql_query(query=query, team=team, query_type="web_path_cleaning_distinct")
    rows = response.results or []
    return int(rows[0][0]) if rows and rows[0] and rows[0][0] is not None else 0


def _extract_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        # strip a ```json … ``` fence
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response contained no JSON object")
    return json.loads(text[start : end + 1])


def call_llm_for_rules(team: Team, paths: list[tuple[str, int]], *, model: str) -> SuggestedRulesResponse:
    client = get_llm_client(product="web_analytics", team_id=team.id)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(paths)},
        ],
        temperature=0.2,
        user=f"team-{team.id}",
    )
    content = completion.choices[0].message.content or ""
    return SuggestedRulesResponse.model_validate(_extract_json(content))


def validate_and_annotate_rules(
    rules: list[SuggestedRule], sampled_paths: list[tuple[str, int]]
) -> list[AnnotatedRule]:
    """Compile each suggested regex with re2 (the same engine ClickHouse `replaceRegexpAll` uses) and
    test-apply it to the real sampled paths. Drop rules that don't compile or match nothing, and
    re-number `order` densely in the model's most-specific-first order."""
    paths = [path for path, _ in sampled_paths]
    annotated: list[AnnotatedRule] = []
    order = 0
    for rule in rules:
        if not rule.regex or not rule.alias:
            continue
        try:
            compiled = re2.compile(rule.regex)
        except re2.error:
            logger.info("path_cleaning_suggestion_invalid_regex", regex=rule.regex)
            continue

        examples: list[dict[str, str]] = []
        match_count = 0
        alias_valid = True
        for path in paths:
            try:
                cleaned = compiled.sub(rule.alias, path)
            except (re2.error, IndexError):
                # LLM produced an alias with a backreference the regex can't satisfy (e.g. `\1` with
                # no capture group). Drop the rule rather than let it fail the whole team's run.
                logger.info("path_cleaning_suggestion_invalid_alias", regex=rule.regex, alias=rule.alias)
                alias_valid = False
                break
            if cleaned != path:
                match_count += 1
                if len(examples) < MAX_EXAMPLES_PER_RULE:
                    examples.append({"before": path, "after": cleaned})

        if not alias_valid or match_count == 0:
            continue

        annotated.append(
            AnnotatedRule(
                regex=rule.regex,
                alias=rule.alias,
                order=order,
                reason=rule.reason,
                match_count=match_count,
                examples=examples,
            )
        )
        order += 1
    return annotated


def generate_suggestions_for_team(
    team: Team,
    *,
    days: int = DEFAULT_SAMPLE_DAYS,
    limit: int = DEFAULT_SAMPLE_LIMIT,
    min_distinct_paths: int = DEFAULT_MIN_DISTINCT_PATHS,
    include_configured: bool = False,
    visited_within_days: int | None = DEFAULT_VISITED_WITHIN_DAYS,
) -> TeamSuggestionResult:
    existing_rules = team.path_cleaning_filters or []
    existing_rule_count = len(existing_rules)

    def _result(
        status: str, rules: list[AnnotatedRule], distinct: int, sampled: int, error: str | None = None
    ) -> TeamSuggestionResult:
        return TeamSuggestionResult(
            team_id=team.id,
            status=status,
            rules=rules,
            sampled_path_count=sampled,
            distinct_path_count=distinct,
            existing_rule_count=existing_rule_count,
            model=_resolve_model() if status in ("generated", "error") else "",
            error=error,
        )

    if existing_rule_count > 0 and not include_configured:
        return _result("skipped_configured", [], 0, 0)

    try:
        # The whole suggestion pipeline rides the health-check framework, so its ClickHouse
        # queries are tagged as such regardless of the caller (API, command, or scheduled check).
        with tags_context(
            product=Product.WEB_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk, org_id=team.organization_id
        ):
            # The activity gate runs a ClickHouse query, so it lives inside the guard with the
            # rest — a transient query failure must surface as this team's error result, not
            # propagate out of a cohort sweep.
            if visited_within_days is not None and not has_recent_pageviews(team, days=visited_within_days):
                return _result("skipped_inactive", [], 0, 0)

            distinct = count_distinct_pathnames(team, days=days)
            if distinct < min_distinct_paths:
                return _result("skipped_low_cardinality", [], distinct, 0)

            paths = sample_pathnames(team, days=days, limit=limit)
            if not paths:
                return _result("skipped_no_paths", [], distinct, 0)

        response = call_llm_for_rules(team, paths, model=_resolve_model())
        annotated = validate_and_annotate_rules(response.rules, paths)
        return _result("generated", annotated, distinct, len(paths))
    except Exception as exc:  # noqa: BLE001 — one bad team must not abort the cohort sweep
        logger.exception("path_cleaning_suggestion_failed", team_id=team.id)
        return _result("error", [], 0, 0, error=f"{type(exc).__name__}: {exc}")


def build_suggestion_payload(result: TeamSuggestionResult) -> dict[str, Any]:
    """The `HealthIssue.payload` shape for a generated suggestion. One place, so the health
    check, the on-demand API, and the frontend banner all agree on the field names.

    `examples` (real sampled paths) are deliberately excluded: health-issue payloads are
    readable with just `health_issue:read`, which must not leak a team's event data."""
    return {
        "rules": [
            {
                "regex": rule.regex,
                "alias": rule.alias,
                "order": rule.order,
                "reason": rule.reason,
                "match_count": rule.match_count,
            }
            for rule in result.rules
        ],
        "model": result.model,
        "sampled_path_count": result.sampled_path_count,
        "distinct_path_count": result.distinct_path_count,
    }


MAX_PREVIEW_EXAMPLES = 20


def preview_rules_on_team(
    team: Team,
    rules: list[AnnotatedRule],
    *,
    days: int = DEFAULT_SAMPLE_DAYS,
    limit: int = DEFAULT_SAMPLE_LIMIT,
    max_examples: int = MAX_PREVIEW_EXAMPLES,
) -> dict[str, Any]:
    """Apply the suggested rules (in order, output feeding the next — exactly how ClickHouse
    applies configured rules) to a fresh sample of the team's top paths. Returns before/after
    pairs for the paths that change, computed on demand and never stored."""
    compiled: list[tuple[Any, str]] = []
    for rule in sorted(rules, key=lambda r: r.order):
        try:
            compiled.append((re2.compile(rule.regex), rule.alias))
        except re2.error:
            logger.info("path_cleaning_preview_invalid_regex", regex=rule.regex)

    with tags_context(
        product=Product.WEB_ANALYTICS, feature=Feature.HEALTH_CHECK, team_id=team.pk, org_id=team.organization_id
    ):
        sampled = sample_pathnames(team, days=days, limit=limit)
    examples: list[dict[str, Any]] = []
    changed = 0
    for path, views in sampled:
        cleaned = path
        for compiled_regex, alias in compiled:
            try:
                cleaned = compiled_regex.sub(alias, cleaned)
            except (re2.error, IndexError):
                continue
        if cleaned != path:
            changed += 1
            if len(examples) < max_examples:
                examples.append({"before": path, "after": cleaned, "views": views})

    return {
        "examples": examples,
        "changed_path_count": changed,
        "sampled_path_count": len(sampled),
    }


def apply_suggestions_to_team(team: Team, rules: list[AnnotatedRule]) -> int:
    """Merge suggested rules into the team's existing `path_cleaning_filters`. Never overwrites: rules
    whose regex already exists are skipped, new ones are appended after the current max order. Returns
    the number of rules actually added."""
    existing = list(team.path_cleaning_filters or [])
    existing_regexes = {f.get("regex") for f in existing}
    next_order = max((int(f.get("order", 0)) for f in existing), default=-1) + 1

    added = 0
    for rule in rules:
        if rule.regex in existing_regexes:
            continue
        existing.append({"regex": rule.regex, "alias": rule.alias, "order": next_order})
        existing_regexes.add(rule.regex)
        next_order += 1
        added += 1

    if added:
        team.path_cleaning_filters = existing
        team.save(update_fields=["path_cleaning_filters"])
    return added
