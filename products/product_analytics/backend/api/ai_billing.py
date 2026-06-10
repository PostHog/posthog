from posthog.models import Team
from posthog.utils import get_instance_region_url


def billable_ai_properties(team: Team, ai_feature: str) -> dict[str, object]:
    properties: dict[str, object] = {
        "ai_product": "product_analytics",
        "ai_feature": ai_feature,
        "$ai_billable": True,
        "team_id": team.id,
    }
    region_url = get_instance_region_url()
    if region_url:
        properties["$group_1"] = region_url
    return properties
