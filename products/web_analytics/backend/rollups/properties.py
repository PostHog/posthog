from posthog.models.property.util import get_property_string_expr


def event_property(name: str) -> str:
    """SQL for a string event property, read from its materialized column when one exists.

    The fills scan a whole day of every team's events, so they must not parse `properties` where
    ClickHouse already stores the value in its own column. The fills span all teams, so they cannot
    go through the HogQL printer, which makes this choice for team queries.
    """
    expression, _ = get_property_string_expr("events", name, f"'{name}'", "properties")
    return expression


def has_event_property(name: str) -> str:
    """SQL that is true when the event sets the property to a non-empty value."""
    return f"{event_property(name)} != ''"
