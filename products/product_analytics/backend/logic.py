from products.product_analytics.backend.models.insight_variable import InsightVariable


def map_stale_to_latest(stale_variables: dict, latest_variables: list[InsightVariable]) -> dict:
    # Keep the variables in an insight up to date based on variable code names that exist
    current_variables = stale_variables
    insight_variables = latest_variables
    final_variables = {}

    # Create a lookup for insight variables by code_name for quick access
    insight_variables_by_code_name = {var.code_name: var for var in insight_variables}

    # For each variable in current_variables, update with data from insight_variables if code_name matches
    for _, v in current_variables.items():
        code_name = v.get("code_name")
        if code_name in insight_variables_by_code_name:
            # Update the variable with corresponding data from insight_variables
            matched_var = insight_variables_by_code_name[code_name]
            # Add attributes from matched_var that can be serialized to JSON
            final_variables[str(matched_var.id)] = {
                **v,
                "code_name": matched_var.code_name,
                "variableId": str(matched_var.id),
            }

    return final_variables


def get_query_specific_instructions(kind: str) -> str:
    if kind == "TrendsQuery":
        return (
            "Focus on identifying significant changes in volume, growth trends, and seasonality. "
            "Compare the current period to the start. Identify which breakdown segment (if any) is driving the trend."
        )
    elif kind == "FunnelsQuery":
        return (
            "Focus on conversion rates between steps. When there are three or more steps, name the step-to-step "
            "transition with the largest loss. When there are only two steps (one transition), describe the single "
            "drop-off directly without superlatives like 'the biggest' or 'the main bottleneck' — there is nothing "
            "to compare it against. Compare conversion across breakdown segments if available."
        )
    elif kind == "RetentionQuery":
        return (
            "Focus on the retention curve shape. Identify when the drop-off stabilizes. "
            "Compare retention rates between different cohorts or breakdown segments."
        )
    elif kind == "StickinessQuery":
        return "Focus on how frequently users engage. Identify if there is a core group of power users."
    elif kind == "LifecycleQuery":
        return "Focus on the balance between new, returning, resurrecting, and dormant users. Identify which group is dominating the total count."

    return "Focus on the most significant patterns and anomalies in the data."
