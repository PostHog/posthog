from django.db import transaction
from django.db.models.functions import Length

from posthog.models.team.team import Team
from posthog.utils import get_safe_cache, safe_cache_add, safe_cache_delete

from products.mcp_analytics.backend.facade.contracts import CustomHarnessRule
from products.mcp_analytics.backend.models import MCPCustomHarness

# Short, because a read that races a save can cache the old rules after the save's delete.
CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS = 5 * 60

RulePairs = tuple[tuple[str, str], ...]


def _cache_key(team_id: int) -> str:
    return f"mcp_analytics:custom_harness_rules:{team_id}"


def _canonical_team_id(team: Team) -> int:
    return team.parent_team_id or team.pk


def _rule_pairs_from_db(team_id: int) -> RulePairs:
    # The first matching rule wins, so the most specific pattern goes first.
    return tuple(
        MCPCustomHarness.objects.for_team(team_id, canonical=True)
        .order_by(Length("match_pattern").desc(), "created_at")
        .values_list("name", "match_pattern")
    )


def custom_harness_rules(team: Team) -> tuple[CustomHarnessRule, ...]:
    team_id = _canonical_team_id(team)
    pairs: RulePairs | None = get_safe_cache(_cache_key(team_id))
    if pairs is None:
        pairs = _rule_pairs_from_db(team_id)
        safe_cache_add(_cache_key(team_id), pairs, CUSTOM_HARNESS_RULES_CACHE_TTL_SECONDS)
    return tuple(CustomHarnessRule(name=name, pattern=pattern) for name, pattern in pairs)


def invalidate_custom_harness_rules(team: Team) -> None:
    # Deleting rather than writing means two concurrent saves cannot store their rules in the wrong order.
    cache_key = _cache_key(_canonical_team_id(team))
    transaction.on_commit(lambda: safe_cache_delete(cache_key))
