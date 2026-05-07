from pathlib import Path


def _load_sql_query(filename: str, order_by: str, order_direction: str) -> str:
    query_path = Path(__file__).parent / filename
    with open(query_path) as f:
        query_template = f.read()
    return query_template.replace("__ORDER_BY__", order_by).replace("__ORDER_DIRECTION__", order_direction)


def get_errors_query(order_by: str = "last_seen", order_direction: str = "DESC") -> str:
    """Load and parameterize the errors normalization query from errors.sql."""
    return _load_sql_query("errors.sql", order_by, order_direction)


def get_sessions_query(order_by: str = "last_seen", order_direction: str = "DESC") -> str:
    """Load and parameterize the sessions aggregation query from sessions.sql."""
    return _load_sql_query("sessions.sql", order_by, order_direction)
