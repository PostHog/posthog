from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_DOCS_URL = "https://docs.develocity.ai/2026.3/reference/develocity-api/"
PAGE_SIZE = 100


@frozen
class BuildEndpoint:
    build_tool: str | None = None
    models: tuple[str, ...] = ()


ENDPOINTS: dict[str, BuildEndpoint] = {
    "builds": BuildEndpoint(),
    "gradle_builds": BuildEndpoint(
        build_tool="gradle",
        models=("gradle-attributes", "gradle-build-cache-performance", "gradle-test-performance"),
    ),
    "maven_builds": BuildEndpoint(
        build_tool="maven",
        models=("maven-attributes", "maven-build-cache-performance", "maven-test-performance"),
    ),
}

PRIMARY_KEYS = ["id"]
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "availableAt",
            "type": IncrementalFieldType.Integer,
            "field": "availableAt",
            "field_type": IncrementalFieldType.Integer,
        }
    ]
    for name in ENDPOINTS
}

INVALID_URL = "Enter an HTTPS Develocity instance URL without a path, query, or embedded credentials."
INVALID_KEY = "Your Develocity access key is invalid or expired. Generate a new key in My settings > Access keys."
MISSING_PERMISSION = 'Your Develocity account needs the "Access build data via the API" permission. Contact your Develocity administrator.'
