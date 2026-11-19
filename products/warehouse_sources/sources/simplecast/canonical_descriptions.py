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
    "seasons": {
        "description": "A season of a Simplecast podcast. Join it to episodes on the podcast ID and the season number.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast the season belongs to.",
            "number": "The season number.",
            "href": "The API URL of the season resource. It ends in the season's ID.",
        },
    },
    "locations": {
        "description": "All-time downloads of a Simplecast podcast by listener country, one row per podcast and country.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "id": "The ID of the country.",
            "name": "The name of the country.",
            "rank": "The country's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads from the country.",
            "downloads_percent": "The country's share of the podcast's downloads.",
            "states": "A link to the state breakdown of the country's downloads.",
        },
    },
    "distribution_channels": {
        "description": "A platform that Simplecast can distribute podcasts to, such as Apple Podcasts or Spotify.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the distribution channel.",
            "name": "The name of the platform.",
            "href": "The API URL of the distribution channel resource.",
        },
    },
    "podcast_distribution_channels": {
        "description": "A distribution channel that was added to a Simplecast podcast, with the podcast's URL on that platform.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "id": "The unique ID of the podcast's distribution channel entry.",
            "podcast_id": "The ID of the podcast.",
            "url": "The URL of the podcast on the platform.",
            "distribution_channel": "The platform, with its ID and name.",
            "href": "The API URL of the podcast's distribution channel entry.",
        },
    },
    "technology_applications": {
        "description": "All-time downloads of a Simplecast podcast by listening application, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The listening application.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_browsers": {
        "description": "All-time downloads of a Simplecast podcast by web browser, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The web browser.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_devices": {
        "description": "All-time downloads of a Simplecast podcast by device model, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The device model.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_device_class": {
        "description": "All-time downloads of a Simplecast podcast by device type (for example phone, desktop or smart speaker), one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The device type.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_listening_methods": {
        "description": "All-time downloads of a Simplecast podcast by listening method, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The listening method.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_network_types": {
        "description": "All-time downloads of a Simplecast podcast by network type, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The network type.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_operating_systems": {
        "description": "All-time downloads of a Simplecast podcast by operating system, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The operating system.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_providers": {
        "description": "All-time downloads of a Simplecast podcast by network provider, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The network provider.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
    "technology_web_players": {
        "description": "All-time downloads of a Simplecast podcast by web player, one row per podcast and value.",
        "docs_url": "https://apidocs.simplecast.com",
        "columns": {
            "podcast_id": "The ID of the podcast.",
            "name": "The web player.",
            "rank": "The value's rank by downloads for the podcast.",
            "downloads_total": "The number of downloads with this value.",
            "downloads_percent": "The value's share of the podcast's downloads.",
        },
    },
}
