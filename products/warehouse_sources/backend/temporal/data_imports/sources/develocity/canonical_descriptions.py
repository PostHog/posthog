from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.develocity.settings import API_DOCS_URL

BUILDS_DESCRIPTIONS: CanonicalDescriptions = {
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

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    **BUILDS_DESCRIPTIONS,
    "build_tests": {
        "description": "Test executions of each build, one row per build, with every test work unit, container, and test case.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "buildId": "The Build Scan identifier of the build that ran the tests.",
            "availableAt": "Time when Develocity finished receiving and processing the build, in milliseconds since the Unix epoch.",
            "summary": "Total and serial test duration, and outcome counts for test cases and test containers.",
            "workUnits": "Test work units of the build, each with its outcome, duration, and nested tests. Every test lists its executions, so retries appear as several executions.",
        },
    },
    "build_failures": {
        "description": "Build and test failures of each build, one row per build. Develocity marks the Failures API as beta.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "buildId": "The Build Scan identifier of the failed or successful build.",
            "availableAt": "Time when Develocity finished receiving and processing the build, in milliseconds since the Unix epoch.",
            "buildToolType": "The tool that ran the build.",
            "gradle": "Build failures with task paths, and test failures, of a Gradle build. Null for other build tools.",
            "maven": "Build failures with goal executions, and test failures, of a Maven build. Null for other build tools.",
            "npm": "Build failures with process names, and test failures, of an npm build. Null for other build tools.",
            "docker": "Build failures with build steps of a Docker build. Null for other build tools.",
        },
    },
}
