"""Lets a product keep the scouts it created for its objects up to date, right before each run.

A product registers a refresher by dotted path, so signals never imports it and nothing loads until a run needs it.
The runner calls `refresh_source_scout` before it loads the scout's skill, so whatever the refresher publishes is
what the run reads.
"""

from django.utils.module_loading import import_string

from products.signals.backend.models import SignalScoutConfig

# `LLMSkill.metadata` keys where a source product records the template a scout's text came from, and that text's hash.
SOURCE_TEMPLATE_METADATA_KEY = "source_template"
SOURCE_TEMPLATE_HASH_METADATA_KEY = "source_template_hash"
SOURCE_TEMPLATE_METADATA_KEYS = frozenset({SOURCE_TEMPLATE_METADATA_KEY, SOURCE_TEMPLATE_HASH_METADATA_KEY})

# source_product -> dotted path of `refresher(team_id: int, skill_name: str, source_id: str) -> None`.
_REFRESHERS: dict[str, str] = {}


def register_source_scout_refresher(source_product: str, refresher_path: str) -> None:
    _REFRESHERS[source_product] = refresher_path


def refresh_source_scout(team_id: int, skill_name: str) -> None:
    """Run the refresher of the product that owns this scout, if it registered one."""
    source = (
        SignalScoutConfig.objects.for_team(team_id)
        .filter(skill_name=skill_name)
        .values_list("source_product", "source_id")
        .first()
    )
    if source is None or not source[0] or not source[1] or source[0] not in _REFRESHERS:
        return
    import_string(_REFRESHERS[source[0]])(team_id, skill_name, source[1])
