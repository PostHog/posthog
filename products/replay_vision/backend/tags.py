"""Tag slug normalization shared across Replay Vision (classifier output, embedding metadata, Max search)."""

import re

# Anything that isn't a-z, 0-9, underscore, or dash collapses to a single underscore.
_SLUG_COLLAPSE_PATTERN = r"[^a-z0-9_-]+"
_SLUG_COLLAPSE_RE = re.compile(_SLUG_COLLAPSE_PATTERN)
# Mirrors `.strip("_")` for the ClickHouse expression below.
_SLUG_STRIP_PATTERN = r"^_+|_+$"


def slugify_tag(value: str) -> str:
    """Lowercase + replace non-[a-z0-9_-] runs with `_` + strip leading/trailing underscores."""
    return _SLUG_COLLAPSE_RE.sub("_", value.lower()).strip("_")


def clickhouse_slugify_sql(column_expr: str) -> str:
    """ClickHouse expression applying `slugify_tag`'s normalization to a string column, so the stored side of a
    tag comparison matches the Python-slugified query side. Built from the same patterns as `slugify_tag` so the
    two stay in sync — edit both here together (one is a regex sub + `.strip`, the other its SQL mirror)."""
    return (
        f"replaceRegexpAll(replaceRegexpAll(lower({column_expr}), '{_SLUG_COLLAPSE_PATTERN}', '_'), "
        f"'{_SLUG_STRIP_PATTERN}', '')"
    )
