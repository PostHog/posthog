from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_CATEGORY_COLUMNS = {
    "id": "Category ID.",
    "name": "Category name.",
}

_UPDATED_MEDIA_COLUMNS = {
    "id": "ID of the media item that was updated.",
    "updated_time": "Date that the media item was updated.",
    "updates": "Types of updates that were made to the media item (addition, deletion, or edit).",
}

_COLLECTION_COLUMNS = {
    "id": "The collection ID.",
    "name": "The name of the collection.",
    "created_time": "When the collection was created.",
    "updated_time": "The last time the collection itself was updated (other than changes to the items in it).",
    "items_updated_time": "The last time this collection's items were updated.",
    "total_item_count": "The number of items in the collection.",
    "cover_item": "The media item shown as the collection's cover.",
    "share_code": "A code that can be used to share the collection.",
    "share_url": "The browser URL that can be used to share the collection.",
}

_LICENSE_COLUMNS = {
    "id": "ID of the download event.",
    "download_time": "Date the media was downloaded the first time.",
    "license": "The name of the license of this download.",
    "is_downloadable": "Whether the media is still downloadable via its downloads endpoint.",
    "metadata": "The metadata that was passed in the original licensing request.",
    "subscription_id": "ID of the subscription used to perform this download.",
    "user": "The user that performed the download.",
}

_COLLECTION_ITEM_COLUMNS = {
    "collection_id": "ID of the collection that contains this item.",
    "id": "ID of the media item in the collection.",
    "added_time": "Date when the item was added to the collection.",
    "media_type": "Type of media in the collection.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "image_categories": {
        "description": "Categories that Shutterstock images can belong to.",
        "docs_url": "https://api-reference.shutterstock.com/#images-list-image-categories",
        "columns": _CATEGORY_COLUMNS,
    },
    "video_categories": {
        "description": "Categories that Shutterstock videos can belong to.",
        "docs_url": "https://api-reference.shutterstock.com/#videos-list-video-categories",
        "columns": _CATEGORY_COLUMNS,
    },
    "images_updated": {
        "description": "Images that were recently added, deleted, or edited in the Shutterstock catalog.",
        "docs_url": "https://api-reference.shutterstock.com/#images-list-updated-images",
        "columns": _UPDATED_MEDIA_COLUMNS,
    },
    "videos_updated": {
        "description": "Videos that were recently added, deleted, or edited in the Shutterstock catalog.",
        "docs_url": "https://api-reference.shutterstock.com/#videos-list-updated-videos",
        "columns": _UPDATED_MEDIA_COLUMNS,
    },
    "image_collections": {
        "description": "The account's image collections (lightboxes).",
        "docs_url": "https://api-reference.shutterstock.com/#images-list-image-collections",
        "columns": _COLLECTION_COLUMNS,
    },
    "video_collections": {
        "description": "The account's video collections (clipboxes).",
        "docs_url": "https://api-reference.shutterstock.com/#videos-list-video-collections",
        "columns": _COLLECTION_COLUMNS,
    },
    "image_collection_items": {
        "description": "Image membership in the account's collections, with one row per collection and image.",
        "docs_url": "https://api-reference.shutterstock.com/#images-get-the-contents-of-image-collections",
        "columns": _COLLECTION_ITEM_COLUMNS,
    },
    "video_collection_items": {
        "description": "Video membership in the account's collections, with one row per collection and video.",
        "docs_url": "https://api-reference.shutterstock.com/#videos-get-the-contents-of-video-collections",
        "columns": _COLLECTION_ITEM_COLUMNS,
    },
    "image_licenses": {
        "description": "The account's image license history: one row per image download event.",
        "docs_url": "https://api-reference.shutterstock.com/#images-list-image-licenses",
        "columns": {**_LICENSE_COLUMNS, "image": "Details of the licensed image."},
    },
    "video_licenses": {
        "description": "The account's video license history: one row per video download event.",
        "docs_url": "https://api-reference.shutterstock.com/#videos-list-video-licenses",
        "columns": {**_LICENSE_COLUMNS, "video": "Details of the licensed video."},
    },
    "audio_licenses": {
        "description": "The account's audio license history, with one row per download event.",
        "docs_url": "https://api-reference.shutterstock.com/#audio-list-audio-licenses",
        "columns": {**_LICENSE_COLUMNS, "audio": "Details of the licensed audio track."},
    },
    "audio_genres": {
        "description": "Genres for Shutterstock audio tracks.",
        "docs_url": "https://api-reference.shutterstock.com/#audio-list-audio-genres",
        "columns": {"name": "Name of the audio genre."},
    },
    "audio_instruments": {
        "description": "Instruments for Shutterstock audio tracks.",
        "docs_url": "https://api-reference.shutterstock.com/#audio-list-audio-instruments",
        "columns": {"name": "Name of the instrument."},
    },
    "audio_moods": {
        "description": "Moods for Shutterstock audio tracks.",
        "docs_url": "https://api-reference.shutterstock.com/#audio-list-audio-moods",
        "columns": {"name": "Name of the audio mood."},
    },
    "subscriptions": {
        "description": "The account's Shutterstock subscriptions and their download allotments.",
        "docs_url": "https://api-reference.shutterstock.com/#users-list-user-subscriptions",
        "columns": {
            "id": "Unique internal identifier for the subscription.",
            "description": "Description of the subscription.",
            "license": "Internal identifier for the type of subscription.",
            "asset_type": "Type of assets associated with this subscription (images, videos, audio, editorial).",
            "expiration_time": "Date the subscription ends.",
            "formats": "List of formats that are licensable for the subscription.",
            "allotment": "Download credit allotment: credits remaining, total credits, and the subscription period.",
            "metadata": "Metadata fields the subscription requires with each licensing request.",
            "price_per_download": "Price per download for the subscription.",
        },
    },
}
