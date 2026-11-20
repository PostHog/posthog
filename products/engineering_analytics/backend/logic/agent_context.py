_FILLED_AGENT_LINE_PATTERN = "(?m)^[*][*]Agent:[*][*][[:blank:]]*[^[:space:]]"
_TEMPLATE_PLACEHOLDER_PATTERN = "(?m)^[*][*]Agent:[*][*][[:blank:]]*tool, model"


def has_agent_context_expr(body_column: str) -> str:
    body = f"ifNull({body_column}, '')"
    return f"(match({body}, '{_FILLED_AGENT_LINE_PATTERN}') AND NOT match({body}, '{_TEMPLATE_PLACEHOLDER_PATTERN}'))"
