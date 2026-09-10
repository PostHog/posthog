from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the AppFollow API v2 documentation (https://docs.api.appfollow.io/reference/overview and
# the per-endpoint response-field references). Partial coverage is fine — anything omitted falls back
# to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "app_collections": {
        "description": "Workspaces (collections) on your AppFollow account, each grouping a set of tracked apps.",
        "docs_url": "https://docs.api.appfollow.io/reference/app_collections_list_api_v2_account_apps_get-1",
        "columns": {
            "id": "Unique collection (workspace) identifier.",
            "title": "Collection display name.",
            "title_normalized": "Normalized collection name used as `collection_name` in other endpoints.",
            "count_apps": "Number of apps in the collection.",
            "countries": "Countries tracked for the collection.",
            "languages": "Languages tracked for the collection.",
            "created": "When the collection was created.",
        },
    },
    "app_lists": {
        "description": "The apps tracked across every collection, including each app's store `ext_id`.",
        "docs_url": "https://docs.api.appfollow.io/reference/list_of_apps_from_the_collection_api_v2_account_apps_app_get-1",
        "columns": {
            "app_id": "AppFollow's internal identifier for the app.",
            "app_collection_id": "Identifier of the collection this app row belongs to.",
            "collection_name": "Normalized name of the collection this app row belongs to.",
            "ext_id": "The app's external store id (App Store / Google Play app id) used to query reviews and ratings.",
            "store": "Store the app is published on (as = App Store, gp = Google Play, ms, am, mc, xs).",
            "count_reviews": "Number of reviews AppFollow has collected for the app.",
            "created": "When the app was added to AppFollow.",
            "watch_url": "AppFollow dashboard URL for the app.",
        },
    },
    "users": {
        "description": "Users on your AppFollow account.",
        "docs_url": "https://docs.api.appfollow.io/reference/users_list_api_v2_account_users_get-1",
        "columns": {
            "id": "Unique user identifier.",
            "email": "User email address.",
            "name": "User display name.",
            "role": "User role on the account.",
            "status": "User account status.",
            "updated": "When the user was last updated.",
        },
    },
    "reviews": {
        "description": "App Store and Google Play reviews for your tracked apps, incrementally synced on the review's last-modified timestamp.",
        "docs_url": "https://docs.api.appfollow.io/reference/reviews_api_v2_reviews_get-1",
        "columns": {
            "id": "AppFollow's internal review identifier.",
            "review_id": "The store's review identifier (unique within an app).",
            "ext_id": "External store id of the app the review belongs to.",
            "app_id": "AppFollow's internal identifier for the app.",
            "store": "Store the review was posted on.",
            "title": "Review title.",
            "content": "Review text.",
            "author": "Review author.",
            "rating": "Star rating the review gave.",
            "rating_prev": "Previous rating, when the review was edited.",
            "date": "When the review was published in the store.",
            "dt": "When the review was written, if provided by the store.",
            "created": "When AppFollow collected the review.",
            "updated": "When the review was last updated (the incremental cursor).",
            "app_version": "App version the review was left on.",
            "locale": "Two-letter country code of the review.",
            "is_answer": "Whether the review has a developer reply.",
            "was_changed": "Whether the review was edited.",
            "user_id": "Store user id of the author, if available.",
        },
    },
    "ratings_history": {
        "description": "Daily star-rating history per app and store, incrementally synced by date.",
        "docs_url": "https://docs.api.appfollow.io/reference/ratings_history_api_v2_meta_ratings_history_get",
        "columns": {
            "ext_id": "External store id of the app.",
            "store": "Store the ratings belong to.",
            "date": "Day the rating snapshot is for.",
            "avg_rating": "Average star rating on that day.",
            "stars": "Total number of ratings on that day.",
            "stars1": "Count of 1-star ratings.",
            "stars2": "Count of 2-star ratings.",
            "stars3": "Count of 3-star ratings.",
            "stars4": "Count of 4-star ratings.",
            "stars5": "Count of 5-star ratings.",
        },
    },
}
