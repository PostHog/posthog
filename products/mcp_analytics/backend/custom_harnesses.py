from django.core.cache import cache

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import CustomHarnessRule
from products.mcp_analytics.backend.models import MCPCustomHarness

logger = structlog.get_logger(__name__)

CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

RulePairs = tuple[tuple[str, str], ...]


def _cache_key(team_id: int) -> str:
    return f"mcp_analytics:custom_harness_rules:{team_id}"


def _canonical_team_id(team: Team) -> int:
    return team.parent_team_id or team.pk


def _rule_pairs_from_db(team_id: int) -> RulePairs:
    return tuple(MCPCustomHarness.objects.for_team(team_id, canonical=True).values_list("name", "match_pattern"))


def _log_cache_error(op_name: str, team_id: int, error: Exception) -> None:
    # This cache is read on every HogQL database build, so a Redis outage must not
    # take down unrelated queries. Postgres is the fallback of record.
    logger.exception(f"mcp_analytics.custom_harness_rules_cache_{op_name}_failed", team_id=team_id)
    capture_exception(error, additional_properties={"tag": "mcp_analytics_custom_harness_rules"})


def custom_harness_rules(team: Team) -> tuple[CustomHarnessRule, ...]:
    team_id = _canonical_team_id(team)
    pairs: RulePairs | None = None
    try:
        pairs = cache.get(_cache_key(team_id))
    except Exception as error:
        _log_cache_error("get", team_id, error)
    if pairs is None:
        pairs = _rule_pairs_from_db(team_id)
        try:
            # `add` never overwrites, so a read that started before a save cannot replace the saved rules.
            cache.add(_cache_key(team_id), pairs, CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS)
        except Exception as error:
            _log_cache_error("add", team_id, error)
    return tuple(CustomHarnessRule(name=name, pattern=pattern) for name, pattern in pairs)


def refresh_custom_harness_rules(team: Team) -> None:
    team_id = _canonical_team_id(team)
    cache.set(_cache_key(team_id), _rule_pairs_from_db(team_id), CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS)
