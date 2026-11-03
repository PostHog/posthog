from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_DOCS_URL = "https://docs.develocity.ai/2026.3/reference/develocity-api/"
PAGE_SIZE = 100


@frozen
class BuildEndpoint:
    build_tool: str | None = None
    models: tuple[str, ...] = ()


@frozen
class BuildChildEndpoint:
    """A per-build endpoint, fetched once for each build the `builds` listing returns."""

    path: str
    params: dict[str, Any]


ENDPOINTS: dict[str, BuildEndpoint | BuildChildEndpoint] = {
    "builds": BuildEndpoint(),
    "gradle_builds": BuildEndpoint(
        build_tool="gradle",
        models=("gradle-attributes", "gradle-build-cache-performance", "gradle-test-performance"),
    ),
    "maven_builds": BuildEndpoint(
        build_tool="maven",
        models=("maven-attributes", "maven-build-cache-performance", "maven-test-performance"),
    ),
    "build_tests": BuildChildEndpoint(path="tests/build/{id}", params={}),
    # Failures is a beta API. maxFailures caps the build and test failure lists separately.
    "build_failures": BuildChildEndpoint(path="failures/builds/{id}", params={"maxFailures": 1000}),
}

AVAILABLE_AT_FIELDS: list[IncrementalField] = [
    {
        "label": "availableAt",
        "type": IncrementalFieldType.Integer,
        "field": "availableAt",
        "field_type": IncrementalFieldType.Integer,
    }
]
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = dict.fromkeys(ENDPOINTS, AVAILABLE_AT_FIELDS)

# A child response carries no build identifier, so the parent build's id becomes the key.
BUILD_ID_FIELD = "buildId"
# Develocity answers this problem type when a build's tool does not produce the requested data.
MODEL_NOT_APPLICABLE = "urn:gradle:enterprise:api:problems:build-model-not-applicable"

INVALID_URL = "Enter an HTTPS Develocity instance URL without a path, query, or embedded credentials."
INVALID_KEY = "Your Develocity access key is invalid or expired. Generate a new key in My settings > Access keys."
MISSING_PERMISSION = 'Your Develocity account needs the "Access build data via the API" permission. Contact your Develocity administrator.'
