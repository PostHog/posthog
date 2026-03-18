from pathlib import Path


def get_errors_query(order_by: str = "last_seen", order_direction: str = "DESC") -> str:
    """
    Load and parameterize the errors normalization query from errors.sql.

    Args:
        order_by: Column to sort by (default: "last_seen")
        order_direction: Sort direction "ASC" or "DESC" (default: "DESC")

    Returns:
        HogQL query string with ORDER BY placeholders substituted.
        The {filters} placeholder is left as-is for HogQL engine to handle.
    """
    query_path = Path(__file__).parent / "errors.sql"
    with open(query_path) as f:
        query_template = f.read()

    # Simple string replacement for ORDER BY placeholders
    # {filters} is left as-is - HogQL engine will handle it
    return query_template.replace("__ORDER_BY__", order_by).replace("__ORDER_DIRECTION__", order_direction)
