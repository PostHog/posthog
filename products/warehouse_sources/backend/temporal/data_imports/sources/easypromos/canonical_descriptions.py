from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Curated from the Easypromos REST API v2 reference (https://easypromos-apiref.redoc.ly/). Keyed by
# the endpoint/schema name from `get_schemas`. Partial coverage is fine — anything omitted falls
# back to LLM enrichment. Fan-out tables carry an injected `promotion_id` column not in the API.
DOCS_BASE = "https://easypromos-apiref.redoc.ly/"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "promotions": {
        "description": "A promotion in an Easypromos account. Always belongs to an organizing brand.",
        "docs_url": DOCS_BASE,
        "columns": {
            "id": "Unique identifier of the promotion.",
            "name": "Name of the promotion.",
            "created": "Date and time the promotion was created. ISO-8601 in UTC.",
            "organizing_brand_id": "Identifier of the organizing brand the promotion belongs to.",
        },
    },
    "organizing_brands": {
        "description": "A brand that organizes promotions. Every promotion belongs to one organizing brand.",
        "docs_url": DOCS_BASE,
        "columns": {
            "id": "Unique identifier of the organizing brand.",
            "name": "Name of the organizing brand.",
        },
    },
    "stages": {
        "description": "Definition of a participation stage in a promotion (a quiz, game, wheel, etc). Always belongs to a promotion.",
        "docs_url": DOCS_BASE,
        "columns": {
            "id": "Unique identifier of the stage within its promotion.",
            "promotion_id": "Identifier of the promotion this stage belongs to (added by PostHog during sync).",
        },
    },
    "users": {
        "description": "A participant registered in a promotion. Always belongs to a promotion.",
        "docs_url": DOCS_BASE,
        "columns": {
            "id": "Unique identifier of the user within its promotion.",
            "promotion_id": "Identifier of the promotion this user registered in (added by PostHog during sync).",
            "created": "Date and time the user registered. ISO-8601 in UTC.",
        },
    },
    "participations": {
        "description": "A participation of a user in a participation stage (e.g. a single game play with points, IP and timestamp). Belongs to a user and a stage.",
        "docs_url": DOCS_BASE,
        "columns": {
            "id": "Unique identifier of the participation within its promotion.",
            "promotion_id": "Identifier of the promotion this participation belongs to (added by PostHog during sync).",
            "created": "Date and time of the participation. ISO-8601 in UTC.",
        },
    },
    "prizes": {
        "description": "Assigned prizes and their winners in a promotion. A prize belongs to the user who won it and a prize type.",
        "docs_url": DOCS_BASE,
        "columns": {
            "id": "Unique identifier of the assigned prize within its promotion.",
            "promotion_id": "Identifier of the promotion this prize belongs to (added by PostHog during sync).",
            "created": "Date and time the prize was assigned. ISO-8601 in UTC.",
        },
    },
    "coin_transactions": {
        "description": "Virtual coin transactions in a promotion — each records an amount, timestamp, coin type and the user performing the transaction.",
        "docs_url": DOCS_BASE,
        "columns": {
            "promotion_id": "Identifier of the promotion this transaction belongs to (added by PostHog during sync).",
        },
    },
    "rankings": {
        "description": "Leaderboard of a promotion: users with their scores in a game-based stage.",
        "docs_url": DOCS_BASE,
        "columns": {
            "promotion_id": "Identifier of the promotion this ranking belongs to (added by PostHog during sync).",
        },
    },
    "points_of_sale": {
        "description": "Points of sale configured in a promotion (e.g. for in-store prize redemption).",
        "docs_url": DOCS_BASE,
        "columns": {
            "promotion_id": "Identifier of the promotion this point of sale belongs to (added by PostHog during sync).",
        },
    },
}
