from pathlib import Path


def get_errors_query(filters: str = "true", order_by: str = "last_seen", order_direction: str = "DESC") -> str:
    """
    Load and parameterize the errors normalization query from errors.sql.

    Args:
        filters: HogQL WHERE clause conditions (default: "true")
        order_by: Column to sort by (default: "last_seen")
        order_direction: Sort direction "ASC" or "DESC" (default: "DESC")

    Returns:
        Complete HogQL query string with parameters substituted
    """
    query_path = Path(__file__).parent / "errors.sql"
    with open(query_path) as f:
        query_template = f.read()

    # Replace template placeholders with actual values
    return query_template.format(filters=filters, orderBy=order_by, orderDirection=order_direction)
