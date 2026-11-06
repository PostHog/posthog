from typing import Any

# The spans API documents span tags under `custom`, and some spans also carry them under `attributes`
# or at the top level. A tag can be nested (`{"error": {"type": ...}}`) or dotted (`"error.type"`).
_TAG_CONTAINERS = ("custom", "attributes")


def _nested_error_type(value: Any) -> str | None:
    if isinstance(value, dict):
        error_type = value.get("type")
        if isinstance(error_type, str) and error_type:
            return error_type
    return None


def span_error_type(row: dict[str, Any]) -> str | None:
    """The span's error type, wherever the spans API put it, or `None`."""
    if error_type := _nested_error_type(row.get("error")):
        return error_type
    for container_name in _TAG_CONTAINERS:
        container = row.get(container_name)
        if not isinstance(container, dict):
            continue
        if error_type := _nested_error_type(container.get("error")):
            return error_type
        dotted = container.get("error.type")
        if isinstance(dotted, str) and dotted:
            return dotted
    return None


def with_span_error_type(row: dict[str, Any]) -> dict[str, Any]:
    """Add an `error_type` column to a flattened span row.

    Every row gets the column, empty when the span has no error type, so the table always has it and
    a query that groups on it cannot fail on an account whose spans keep the error somewhere else.
    """
    row["error_type"] = span_error_type(row)
    return row
