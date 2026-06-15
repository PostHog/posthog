"""Tag slug normalization shared across Replay Vision (classifier output, embedding metadata, Max search)."""

import re

# Anything that isn't a-z, 0-9, underscore, or dash collapses to a single underscore.
_FREEFORM_NORMALIZE_RE = re.compile(r"[^a-z0-9_-]+")


def slugify_tag(value: str) -> str:
    """Lowercase + replace non-[a-z0-9_-] runs with `_` + strip leading/trailing underscores."""
    return _FREEFORM_NORMALIZE_RE.sub("_", value.lower()).strip("_")
