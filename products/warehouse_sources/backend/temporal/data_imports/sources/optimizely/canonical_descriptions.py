"""Canonical, documentation-sourced descriptions for Optimizely endpoints and columns.

Sourced from the official Optimizely Web Experimentation REST API v2 reference
(https://library.optimizely.com/docs/api/app/v2/index.html). Keyed by the endpoint names in
`settings.py` `OPTIMIZELY_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Optimizely table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields shared by most Optimizely v2 objects; merged into each entry so we don't repeat them.
_COMMON_COLUMNS = {
    "id": "Unique numeric identifier for the object.",
    "name": "The object's name.",
    "created": "Time at which the object was created.",
    "last_modified": "Time at which the object was last modified.",
}


def _columns(**overrides: str) -> dict[str, str]:
    return {**_COMMON_COLUMNS, **overrides}


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A container for experiments, audiences, events, and pages within an Optimizely account.",
        "docs_url": "https://library.optimizely.com/docs/api/app/v2/index.html#tag/Projects",
        "columns": _columns(
            account_id="ID of the account the project belongs to.",
            description="Description of the project.",
            platform="The project's platform (e.g. web, custom).",
            status="Whether the project is active or archived.",
            project_javascript="Custom JavaScript applied to all pages in the project.",
            web_snippet="Web snippet configuration (e.g. enable_force_variation, library, code revision).",
        ),
    },
    "experiments": {
        "description": "An A/B test or experiment that splits traffic across variations to measure impact.",
        "docs_url": "https://library.optimizely.com/docs/api/app/v2/index.html#tag/Experiments",
        "columns": _columns(
            project_id="ID of the project the experiment belongs to.",
            description="Description of the experiment.",
            status="Lifecycle status of the experiment (e.g. running, paused, not_started, archived, concluded).",
            type="Type of experiment (e.g. a/b, multivariate, personalization).",
            variations="The variations traffic is split across in the experiment.",
            metrics="Metrics tracked to measure the experiment's results.",
            audience_conditions="Conditions defining which visitors are eligible for the experiment.",
            campaign_id="ID of the campaign this experiment belongs to, if any.",
            holdback="Percentage of traffic held back from the experiment.",
            earliest="Earliest time the experiment started serving.",
            latest="Latest time the experiment served.",
        ),
    },
    "audiences": {
        "description": "A targetable segment of visitors defined by attribute and behavior conditions.",
        "docs_url": "https://library.optimizely.com/docs/api/app/v2/index.html#tag/Audiences",
        "columns": _columns(
            project_id="ID of the project the audience belongs to.",
            description="Description of the audience.",
            conditions="Logical conditions that define which visitors belong to the audience.",
            archived="Whether the audience has been archived.",
            segmentation="Whether the audience is used for segmentation.",
        ),
    },
    "events": {
        "description": "A tracked visitor action (click, pageview, or custom event) used as an experiment metric.",
        "docs_url": "https://library.optimizely.com/docs/api/app/v2/index.html#tag/Events",
        "columns": _columns(
            project_id="ID of the project the event belongs to.",
            description="Description of the event.",
            event_type="Type of event (e.g. click, custom, pageview).",
            key="API key used to reference the event when tracking.",
            page_id="ID of the page this event is associated with, if any.",
            category="Category the event is grouped under (e.g. add_to_cart, purchase, other).",
            archived="Whether the event has been archived.",
        ),
    },
    "pages": {
        "description": "A definition of a page or set of URLs where experiments and events can run.",
        "docs_url": "https://library.optimizely.com/docs/api/app/v2/index.html#tag/Pages",
        "columns": _columns(
            project_id="ID of the project the page belongs to.",
            edit_url="URL of the page used when editing in the visual editor.",
            conditions="URL-matching conditions that define when the page is considered active.",
            activation_type="How the page activates (e.g. immediate, manual, polling, callback).",
            category="Category the page is grouped under (e.g. article, cart, home, search).",
            archived="Whether the page has been archived.",
        ),
    },
    "campaigns": {
        "description": "A personalization campaign that delivers experiences to targeted audiences across pages.",
        "docs_url": "https://library.optimizely.com/docs/api/app/v2/index.html#tag/Campaigns",
        "columns": _columns(
            project_id="ID of the project the campaign belongs to.",
            description="Description of the campaign.",
            status="Lifecycle status of the campaign (e.g. active, paused, draft, archived).",
            type="Type of campaign (e.g. a/b, personalization).",
            experiment_ids="IDs of the experiments (experiences) that make up the campaign.",
            page_ids="IDs of the pages the campaign runs on.",
            metrics="Metrics tracked to measure the campaign's results.",
            holdback="Percentage of traffic held back from the campaign.",
            earliest="Earliest time the campaign started serving.",
            latest="Latest time the campaign served.",
        ),
    },
}
