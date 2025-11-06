from collections import defaultdict

from posthog.models.action.action import Action, ActionStepJSON, ActionStepMatching

from .property_filters import (
    PropertyFilterCollectionDescriber,
    PropertyFilterTaxonomyEntry,
    retrieve_hardcoded_taxonomy,
)

ACTION_MATCH_FILTER_VERBOSE_NAME: dict[ActionStepMatching, str] = {
    "regex": "matches regex",
    "exact": "matches exactly",
    "contains": "contains",
}


class ActionSummarizer:
    _action: Action
    _taxonomy: set[PropertyFilterTaxonomyEntry]
    _step_descriptions: list[str]

    def __init__(self, action: Action):
        self._action = action
        self._taxonomy = set()
        self._step_descriptions = []

        for index, step in enumerate(self._action.steps):
            step_desc, used_events = self._describe_action_step(step, index)
            self._step_descriptions.append(step_desc)
            self._taxonomy.update(used_events)

    @property
    def summary(self) -> str:
        steps = "\n\nOR\n\n".join(self._step_descriptions)
        description = f"Name: {self._action.name}\nDescription: {self._action.description or '-'}\n\n{steps}"
        return description

    @property
    def taxonomy_description(self) -> str:
        groups: dict[str, list[PropertyFilterTaxonomyEntry]] = defaultdict(list)
        for taxonomy in self._taxonomy:
            groups[taxonomy.group_verbose_name].append(taxonomy)

        group_descriptions = []
        for group, taxonomies in groups.items():
            description = f"Description of {group} for your reference:\n"
            description += "\n".join([f"- `{taxonomy.key}`: {taxonomy.description}" for taxonomy in taxonomies])
            group_descriptions.append(description)

        description = "\n\n".join(group_descriptions)
        return description

    def _describe_action_step(self, step: ActionStepJSON, index: int) -> tuple[str, set[PropertyFilterTaxonomyEntry]]:
        taxonomy: set[PropertyFilterTaxonomyEntry] = set()
        description: list[str] = []

        if step.event:
            description.append(f"event is `{step.event}`")
            if event_description := retrieve_hardcoded_taxonomy("events", step.event):
                taxonomy.add(PropertyFilterTaxonomyEntry(group="events", key=step.event, description=event_description))
        if step.selector:
            html_desc = f"element matches HTML selector `{step.selector}`"
            description.append(html_desc)
        if step.tag_name:
            tag_desc = f"element tag is `{step.tag_name}`"
            description.append(tag_desc)
        if step.text:
            match_filter: ActionStepMatching = step.text_matching or "exact"
            text_desc = f"element text {ACTION_MATCH_FILTER_VERBOSE_NAME[match_filter]} `{step.text}`"
            description.append(text_desc)
        if step.href:
            match_filter = step.href_matching or "exact"
            href_desc = f"element `href` attribute {ACTION_MATCH_FILTER_VERBOSE_NAME[match_filter]} `{step.href}`"
            description.append(href_desc)
        if step.url:
            match_filter = step.url_matching or "contains"
            url_desc = f"the URL of event {ACTION_MATCH_FILTER_VERBOSE_NAME[match_filter]} `{step.url}`"
            description.append(url_desc)

        if step.properties:
            property_desc, used_properties = PropertyFilterCollectionDescriber(filters=step.properties).describe()
            description.append(property_desc)
            taxonomy.update(used_properties)

        conditions = " AND ".join(description)
        return f"Match group {index + 1}: {conditions}", taxonomy
