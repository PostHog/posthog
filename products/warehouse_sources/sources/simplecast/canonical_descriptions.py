from products.warehouse_sources.sources.sdk import CanonicalDescriptions

# Descriptions sourced from the Simplecast API docs (https://apidocs.simplecast.com).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "podcasts": {
        "description": "A podcast (show) hosted on Simplecast that the account's token can access.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the podcast.",
            "title": "The podcast's title.",
            "account_id": "The ID of the account that owns the podcast.",
            "status": "The publication status of the podcast.",
            "episodes": "A reference to the podcast's episodes collection.",
            "created_at": "When the podcast was created.",
            "updated_at": "When the podcast was last updated.",
            "href": "The API URL of the podcast resource.",
        },
    },
    "episodes": {
        "description": "An episode created on a Simplecast podcast, in any status (draft, scheduled, published or private).",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the episode.",
            "podcast_id": "The ID of the podcast the episode belongs to.",
            "title": "The episode's title.",
            "number": "The episode number.",
            "season": "The season the episode belongs to, with its number.",
            "type": "The episode type: full, trailer or bonus.",
            "status": "The publication status of the episode.",
            "published_at": "When the episode was published.",
            "scheduled_for": "When the episode is scheduled to publish, if scheduled.",
            "updated_at": "When the episode was last updated.",
        },
    },
    "downloads": {
        "description": "Daily downloads of a Simplecast podcast, one row per podcast and day since the podcast was published.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "interval": "The day the downloads were counted for.",
            "downloads_total": "The number of downloads on that day.",
            "downloads_percent": "The day's share of the podcast's downloads over the whole period.",
        },
    },
    "listeners": {
        "description": "Daily unique listeners of a Simplecast podcast, one row per podcast and day since the podcast was published.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "interval": "The day the unique listeners were counted for.",
            "total": "The number of unique listeners on that day.",
            "percent": "The day's share of the podcast's unique listeners over the whole period.",
        },
    },
    "episode_downloads": {
        "description": "All-time downloads of each episode of a Simplecast podcast.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the episode.",
            "podcast_id": "The ID of the podcast the episode belongs to.",
            "title": "The episode's title.",
            "number": "The episode number.",
            "type": "The episode type: full, trailer or bonus.",
            "published_at": "When the episode was published.",
            "downloads": "The episode's downloads, with the count under `total`.",
        },
    },
    "episode_listeners": {
        "description": "All-time unique listeners of each episode of a Simplecast podcast.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the episode.",
            "podcast_id": "The ID of the podcast the episode belongs to.",
            "title": "The episode's title.",
            "number": "The episode number.",
            "type": "The episode type: full, trailer or bonus.",
            "published_at": "When the episode was published.",
            "listeners": "The episode's unique listeners, with the count under `total`.",
        },
    },
}
