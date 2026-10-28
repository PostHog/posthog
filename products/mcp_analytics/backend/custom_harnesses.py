from django.core.cache import cache

from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import CustomHarnessRule
from products.mcp_analytics.backend.models import MCPCustomHarness

CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

RulePairs = tuple[tuple[str, str], ...]


def _cache_key(team_id: int) -> str:
    return f"mcp_analytics:custom_harness_rules:{team_id}"


def _canonical_team_id(team: Team) -> int:
    return team.parent_team_id or team.pk


def _rule_pairs_from_db(team_id: int) -> RulePairs:
    return tuple(MCPCustomHarness.objects.for_team(team_id, canonical=True).values_list("name", "match_pattern"))


def custom_harness_rules(team: Team) -> tuple[CustomHarnessRule, ...]:
    team_id = _canonical_team_id(team)
    pairs: RulePairs | None = cache.get(_cache_key(team_id))
    if pairs is None:
        pairs = _rule_pairs_from_db(team_id)
        # `add` never overwrites, so a read that started before a save cannot replace the saved rules.
        cache.add(_cache_key(team_id), pairs, CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS)
    return tuple(CustomHarnessRule(name=name, pattern=pattern) for name, pattern in pairs)


def refresh_custom_harness_rules(team: Team) -> None:
    team_id = _canonical_team_id(team)
    cache.set(_cache_key(team_id), _rule_pairs_from_db(team_id), CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS)
