# Hand-written GraphQL documents against the dbt Discovery API (the metadata service), which is a
# separate API from the Admin API the rest of this source reads. Field sets are kept to scalars and
# the well-known nested execution/freshness objects: the docs warn that nested nodes, raw code and
# catalog columns count against a per-query complexity limit, so those are left out deliberately.
#
# https://docs.getdbt.com/docs/dbt-cloud-apis/discovery-schema-environment-applied-models

# Cheap probe for the Discovery URL: a bad token is rejected at the gateway before any resolver
# runs, so this never depends on which permission set the token carries.
DISCOVERY_VALIDATION_QUERY = "query { __typename }"

_EXECUTION_INFO = """
            executionInfo {
                lastRunId
                lastRunStatus
                lastRunError
                lastRunGeneratedAt
                lastSuccessRunId
                lastJobDefinitionId
                compileStartedAt
                compileCompletedAt
                executeStartedAt
                executeCompletedAt
                executionTime
                runElapsedTime
                runGeneratedAt
            }"""

MODELS_QUERY = (
    """
query AppliedModels($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            models(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        uniqueId
                        name
                        description
                        resourceType
                        packageName
                        filePath
                        fqn
                        database
                        schema
                        alias
                        relationName
                        materializedType
                        modelingLayer
                        language
                        access
                        group
                        tags
                        meta
                        config
                        contractEnforced
                        columnCount
                        latestVersion
                        version
                        releaseVersion
                        deprecationDate
                        isDescriptionInherited
                        dbtVersion
                        accountId
                        projectId
                        environmentId"""
    + _EXECUTION_INFO
    + """
                    }
                }
            }
        }
    }
}"""
)

TESTS_QUERY = """
query AppliedTests($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            tests(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        uniqueId
                        name
                        description
                        resourceType
                        testType
                        lastKnownResult
                        columnName
                        model
                        testedNodeUniqueId
                        filePath
                        fqn
                        tags
                        meta
                        config
                        dbtVersion
                        accountId
                        projectId
                        environmentId
                        executionInfo {
                            lastRunId
                            lastRunStatus
                            lastRunError
                            lastRunFailures
                            lastRunGeneratedAt
                            lastSuccessRunId
                            lastJobDefinitionId
                            compileStartedAt
                            compileCompletedAt
                            executeStartedAt
                            executeCompletedAt
                            executionTime
                            runElapsedTime
                            runGeneratedAt
                        }
                    }
                }
            }
        }
    }
}"""

SOURCES_QUERY = """
query AppliedSources($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            sources(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        uniqueId
                        name
                        description
                        resourceType
                        sourceName
                        sourceDescription
                        identifier
                        loader
                        database
                        schema
                        filePath
                        fqn
                        tags
                        meta
                        columnCount
                        dbtVersion
                        accountId
                        projectId
                        environmentId
                        freshness {
                            freshnessChecked
                            freshnessStatus
                            freshnessJobDefinitionId
                            freshnessRunId
                            freshnessRunGeneratedAt
                            maxLoadedAt
                            maxLoadedAtTimeAgoInS
                            snapshottedAt
                        }
                    }
                }
            }
        }
    }
}"""

SNAPSHOTS_QUERY = (
    """
query AppliedSnapshots($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            snapshots(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        uniqueId
                        name
                        description
                        resourceType
                        packageName
                        filePath
                        fqn
                        database
                        schema
                        alias
                        tags
                        meta
                        config
                        columnCount
                        dbtVersion
                        accountId
                        projectId
                        environmentId"""
    + _EXECUTION_INFO
    + """
                    }
                }
            }
        }
    }
}"""
)

# SeedAppliedStateNode carries no `config`, and its executionInfo adds `lastRunSkip`, so the seed
# field set is spelled out rather than sharing the model/snapshot one.
SEEDS_QUERY = """
query AppliedSeeds($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            seeds(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        uniqueId
                        name
                        description
                        resourceType
                        packageName
                        filePath
                        fqn
                        database
                        schema
                        alias
                        tags
                        meta
                        columnCount
                        dbtVersion
                        accountId
                        projectId
                        environmentId
                        executionInfo {
                            lastRunId
                            lastRunStatus
                            lastRunError
                            lastRunSkip
                            lastRunGeneratedAt
                            lastSuccessRunId
                            lastJobDefinitionId
                            compileStartedAt
                            compileCompletedAt
                            executeStartedAt
                            executeCompletedAt
                            executionTime
                            runElapsedTime
                            runGeneratedAt
                        }
                    }
                }
            }
        }
    }
}"""

EXPOSURES_QUERY = """
query AppliedExposures($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            exposures(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges {
                    node {
                        uniqueId
                        name
                        label
                        description
                        resourceType
                        exposureType
                        maturity
                        url
                        ownerName
                        ownerEmail
                        packageName
                        filePath
                        fqn
                        tags
                        meta
                        manifestGeneratedAt
                        dbtVersion
                        accountId
                        projectId
                        environmentId
                    }
                }
            }
        }
    }
}"""

# modelHistoricalRuns takes one model at a time, so the model list is walked first to collect the
# unique IDs to ask about.
MODEL_UNIQUE_IDS_QUERY = """
query AppliedModelUniqueIds($environmentId: BigInt!, $first: Int!, $after: String) {
    environment(id: $environmentId) {
        applied {
            models(first: $first, after: $after) {
                pageInfo { hasNextPage endCursor }
                edges { node { uniqueId } }
            }
        }
    }
}"""

MODEL_HISTORICAL_RUNS_QUERY = """
query ModelHistoricalRuns($environmentId: BigInt!, $uniqueId: String!, $lastRunCount: Int!) {
    environment(id: $environmentId) {
        applied {
            modelHistoricalRuns(uniqueId: $uniqueId, lastRunCount: $lastRunCount) {
                uniqueId
                name
                alias
                database
                schema
                resourceType
                materializedType
                language
                packageName
                runId
                jobId
                invocationId
                threadId
                status
                error
                skip
                compileStartedAt
                compileCompletedAt
                executeStartedAt
                executeCompletedAt
                executionTime
                runElapsedTime
                runGeneratedAt
                dbtVersion
                accountId
                projectId
                environmentId
            }
        }
    }
}"""
