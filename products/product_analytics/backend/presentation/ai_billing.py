def billable_ai_properties(team_id: int, ai_feature: str) -> dict[str, object]:
    return {
        "ai_product": "product_analytics",
        "ai_feature": ai_feature,
        "$ai_billable": True,
        "team_id": team_id,
    }
