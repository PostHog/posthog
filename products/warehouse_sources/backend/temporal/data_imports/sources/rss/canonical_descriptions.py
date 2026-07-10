from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the RSS.com Core API v4 OpenAPI spec (https://api.rss.com/v4/docs).
# Partial coverage is fine — uncovered columns fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "podcasts": {
        "description": "A podcast hosted on your RSS.com account.",
        "docs_url": "https://api.rss.com/v4/docs",
        "columns": {
            "id": "The unique ID of the podcast.",
            "slug": "The URL slug of the podcast.",
            "title": "The title of the podcast.",
            "language": "The ISO 639-1 language code of the podcast.",
            "role": "Your role on the podcast (e.g. owner or collaborator).",
            "hibernated": "Whether the podcast is hibernated (paused hosting).",
            "cover_url": "Public URL of the podcast cover image, if any.",
            "redirect_url": "The URL the podcast's RSS feed redirects to, if any.",
            "timestamp_created": "When the podcast was created.",
            "timestamp_updated": "When the podcast was last updated.",
        },
    },
    "episodes": {
        "description": "An episode of a podcast hosted on your RSS.com account.",
        "docs_url": "https://api.rss.com/v4/docs",
        "columns": {
            "id": "The unique ID of the episode within its podcast.",
            "podcast_id": "The ID of the podcast the episode belongs to.",
            "title": "The title of the episode.",
            "description": "The description of the episode, also known as episode notes.",
            "status": "The publishing status of the episode: draft, scheduled, or published.",
            "duration": "The episode duration in seconds.",
            "publish_datetime": "The publication date and time of the episode.",
            "schedule_datetime": "When the episode is scheduled for publishing, if scheduled.",
            "itunes_explicit": "Whether the episode includes explicit content. Null when unset.",
            "itunes_episode": "The Apple Podcasts episode number.",
            "itunes_season": "The Apple Podcasts season number.",
            "itunes_episode_type": "The Apple Podcasts episode type: full, trailer, or bonus.",
            "custom_link": "A custom link used as the episode website in the RSS feed.",
            "cover_url": "Public URL of the episode cover image, if any.",
            "audio_url": "Public URL to listen to or download the episode audio.",
            "audio_preview_url": "Private URL to preview the episode audio before publication.",
            "video_url": "Public URL to watch or download the episode video.",
            "video_preview_url": "Private URL to preview the episode video before publication.",
            "processing": "Status of the processing jobs associated with the episode.",
            "resources": "Status of the child resources associated with the episode.",
            "locations": "Locations assigned to the episode.",
            "keywords": "Keywords assigned to the episode.",
            "apple_episode_access_type": "Apple Delegated Delivery access type of the episode.",
            "dashboard_url": "The RSS.com dashboard URL for the episode.",
            "website_url": "The RSS.com website URL for the episode.",
            "youtube_video_url": "The URL of the YouTube video generated from the episode.",
            "transcript_url": "The URL of the transcript for the episode.",
            "alternate_enclosures": "Alternate media enclosures for the episode.",
            "ai_content": "Whether the episode was made with AI.",
            "guid": "The GUID of the episode, used in the RSS feed.",
        },
    },
    "categories": {
        "description": "A podcast category available on RSS.com (Apple Podcasts taxonomy).",
        "docs_url": "https://api.rss.com/v4/docs",
        "columns": {
            "id": "The unique ID of the category.",
            "label": "The category label.",
            "localized_label": "The category label localized to your account language.",
        },
    },
}
