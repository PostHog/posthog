"""Tag slug normalization shared by scout findings and scout configs.

Tags are lowercase kebab-case so a vocabulary converges instead of fragmenting on casing and
punctuation (`cost_spike` vs `Cost Spike` vs `cost-spike`). Both the emit path (tags an agent
attaches to a finding) and the config API (labels a person puts on a scout) normalize through
here, so the two read alike and a person filtering the fleet by `revenue` types the same thing
a scout would have written.
"""

import re

_TAG_SEPARATORS = re.compile(r"[\s_]+")
_TAG_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
_TAG_HYPHEN_RUNS = re.compile(r"-{2,}")


def slugify_tag(raw: str) -> str:
    """Lowercase kebab-case slug for one tag, or `""` if nothing survives normalization.

    Callers decide what an empty result means — the emit path rejects it so an agent never
    believes a tag stuck when it didn't, and the config API does the same for a person.
    """
    slug = _TAG_SEPARATORS.sub("-", raw.strip().lower())
    slug = _TAG_INVALID_CHARS.sub("", slug)
    return _TAG_HYPHEN_RUNS.sub("-", slug).strip("-")
