# Hand-written GraphQL queries against the Dagster+ (Dagster Cloud) webserver schema.
# The schema is explicitly documented as internal-webserver-oriented and subject to breaking
# changes, so field sets are kept lean and defensive (scalars + well-known nested shapes only).

# Cheap, permission-free probe used by validate_credentials: a bad token 401s at the gateway
# before any resolver runs, so this never depends on which scopes the token carries.
VALIDATION_QUERY = "query { __typename }"

RUNS_QUERY = """
query PaginatedRuns($limit: Int!, $cursor: String, $filter: RunsFilter) {
    runsOrError(limit: $limit, cursor: $cursor, filter: $filter) {
        __typename
        ... on Runs {
            results {
                runId
                jobName
                pipelineName
                status
                mode
                creationTime
                startTime
                endTime
                updateTime
                tags { key value }
                repositoryOrigin { id repositoryName repositoryLocationName }
                assetSelection { path }
            }
        }
        ... on InvalidPipelineRunsFilterError { message }
        ... on PythonError { message }
    }
}"""

BACKFILLS_QUERY = """
query PaginatedBackfills($limit: Int!, $cursor: String) {
    partitionBackfillsOrError(limit: $limit, cursor: $cursor) {
        __typename
        ... on PartitionBackfills {
            results {
                id
                status
                timestamp
                endTimestamp
                numPartitions
                partitionSetName
                jobName
                isAssetBackfill
                title
                description
                user
            }
        }
        ... on PythonError { message }
    }
}"""

ASSETS_QUERY = """
query PaginatedAssets($limit: Int!, $cursor: String) {
    assetsOrError(limit: $limit, cursor: $cursor) {
        __typename
        ... on AssetConnection {
            cursor
            nodes {
                id
                key { path }
            }
        }
        ... on PythonError { message }
    }
}"""
