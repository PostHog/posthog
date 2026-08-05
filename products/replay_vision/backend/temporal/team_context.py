"""Customer product context for scanner prompts: Max core memory + event definition descriptions.

Both sources are customer-authored text rendered into the trusted preamble, so everything is
sanitized (control chars stripped, whitespace collapsed, length-capped) before it is stored.
"""

from posthog.llm.semantic_enrichment import get_team_business_context
from posthog.models import Team
from posthog.settings import EE_AVAILABLE
from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP

# CoreMemory.text is model-capped at 10k chars; cap lower since the preamble is resent on every scan step.
_MAX_PRODUCT_CONTEXT_LEN = 4000
_MAX_EVENT_DESCRIPTIONS = 50
# Mirrors Max's MAX_EVENT_DESCRIPTION_LENGTH in ee/hogai/utils/helpers.py.
_MAX_EVENT_DESCRIPTION_LEN = 500
# Bound the name list sent to Postgres when a session emits a pathological number of distinct events.
_MAX_LOOKUP_NAMES = 300

# The model already knows built-in events, and the preamble explains the key ones by hand.
_CORE_EVENT_NAMES = frozenset(CORE_FILTER_DEFINITIONS_BY_GROUP["events"])


def _sanitize(text: str, max_len: int) -> str:
    cleaned = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned


def fetch_product_context(team: Team) -> str:
    """The team's Max core memory, falling back to the project's (deprecated) product description; "" when neither exists."""
    text = get_team_business_context(team)
    if not text:
        text = (team.project.product_description or "").strip()
    return _sanitize(text, _MAX_PRODUCT_CONTEXT_LEN)


def fetch_event_descriptions(team_id: int, event_names_by_frequency: list[str]) -> dict[str, str]:
    """Customer-written descriptions for this session's custom events, keyed by name in the given order.

    Descriptions only exist on the enterprise EventDefinition model, so this is a no-op on OSS builds.
    """
    if not EE_AVAILABLE:
        return {}
    from ee.models.event_definition import EnterpriseEventDefinition  # noqa: PLC0415 — absent from OSS builds

    # A backtick in a name would escape the prompt's inline-code fencing; drop such names rather than escape.
    custom_names = [name for name in event_names_by_frequency if name not in _CORE_EVENT_NAMES and "`" not in name][
        :_MAX_LOOKUP_NAMES
    ]
    if not custom_names:
        return {}

    found = dict(
        EnterpriseEventDefinition.objects.filter(team_id=team_id, name__in=custom_names)
        .exclude(description__isnull=True)
        .exclude(description="")
        .values_list("name", "description")
    )
    described: dict[str, str] = {}
    for name in custom_names:
        description = found.get(name)
        if not description:
            continue
        sanitized = _sanitize(description, _MAX_EVENT_DESCRIPTION_LEN)
        if not sanitized:
            continue
        described[name] = sanitized
        if len(described) >= _MAX_EVENT_DESCRIPTIONS:
            break
    return described
