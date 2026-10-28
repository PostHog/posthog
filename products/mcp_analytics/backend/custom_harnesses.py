from posthog.models.team.team import Team

from products.mcp_analytics.backend.facade.contracts import CustomHarnessRule
from products.mcp_analytics.backend.models import MCPCustomHarness


def custom_harness_rules(team: Team) -> tuple[CustomHarnessRule, ...]:
    return tuple(
        CustomHarnessRule(name=name, pattern=pattern)
        for name, pattern in MCPCustomHarness.objects.for_team(team.parent_team_id or team.pk, canonical=True).values_list("name", "match_pattern")
    )
