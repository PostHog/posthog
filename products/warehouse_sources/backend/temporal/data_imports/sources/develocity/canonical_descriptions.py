from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": description,
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "The Build Scan identifier.",
            "availableAt": "Time when Develocity finished receiving and processing the build, in milliseconds since the Unix epoch.",
            "buildToolType": "The tool that ran the build.",
            "buildToolVersion": "The version of the tool that ran the build.",
            "buildAgentVersion": "The version of the build agent.",
            **(
                {
                    "models": "Build attributes, cache performance, and test performance models, including reported model errors."
                }
                if name != "builds"
                else {}
            ),
        },
    }
    for name, description in {
        "builds": "Build Scans received by Develocity, across all build tools.",
        "gradle_builds": "Gradle Build Scans with build attributes, cache performance, and test performance.",
        "maven_builds": "Maven Build Scans with build attributes, cache performance, and test performance.",
    }.items()
}
