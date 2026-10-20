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

# Fan-out parent walk: every schedule, sensor, instigation state and asset node is scoped to a
# code location + repository, and only `repositoriesOrError` enumerates them.
REPOSITORIES_QUERY = """
query Repositories {
    repositoriesOrError {
        __typename
        ... on RepositoryConnection {
            nodes {
                id
                name
                location { name }
            }
        }
        ... on RepositoryNotFoundError { message }
        ... on PythonError { message }
    }
}"""

SCHEDULES_QUERY = """
query RepositorySchedules($repositoryName: String!, $repositoryLocationName: String!) {
    schedulesOrError(
        repositorySelector: {
            repositoryName: $repositoryName
            repositoryLocationName: $repositoryLocationName
        }
    ) {
        __typename
        ... on Schedules {
            results {
                id
                name
                cronSchedule
                pipelineName
                mode
                executionTimezone
                description
                defaultStatus
                scheduleState { id selectorId status instigationType }
                assetSelection { assetSelectionString assetKeys { path } }
                tags { key value }
            }
        }
        ... on RepositoryNotFoundError { message }
        ... on PythonError { message }
    }
}"""

SENSORS_QUERY = """
query RepositorySensors($repositoryName: String!, $repositoryLocationName: String!) {
    sensorsOrError(
        repositorySelector: {
            repositoryName: $repositoryName
            repositoryLocationName: $repositoryLocationName
        }
    ) {
        __typename
        ... on Sensors {
            results {
                id
                name
                jobOriginId
                sensorType
                description
                defaultStatus
                minIntervalSeconds
                targets { pipelineName mode }
                sensorState { id selectorId status instigationType }
                assetSelection { assetSelectionString assetKeys { path } }
                metadata { assetKeys { path } }
                tags { key value }
            }
        }
        ... on RepositoryNotFoundError { message }
        ... on PythonError { message }
    }
}"""

INSTIGATION_STATES_QUERY = """
query RepositoryInstigationStates($repositoryID: String!) {
    instigationStatesOrError(repositoryID: $repositoryID) {
        __typename
        ... on InstigationStates {
            results {
                id
                selectorId
                name
                instigationType
                status
                repositoryName
                repositoryLocationName
                runsCount
                typeSpecificData {
                    __typename
                    ... on ScheduleData { cronSchedule startTimestamp }
                    ... on SensorData { lastTickTimestamp lastRunKey lastCursor }
                }
            }
        }
        ... on PythonError { message }
    }
}"""

# `instigationStateOrError` takes the state's own CompoundID as `id`, which disambiguates a
# schedule and a sensor that share a name inside one repository.
INSTIGATION_TICKS_QUERY = """
query InstigationTicks(
    $repositoryName: String!
    $repositoryLocationName: String!
    $instigationName: String!
    $instigationStateId: String
    $limit: Int!
    $beforeTimestamp: Float
    $afterTimestamp: Float
) {
    instigationStateOrError(
        instigationSelector: {
            repositoryName: $repositoryName
            repositoryLocationName: $repositoryLocationName
            name: $instigationName
        }
        id: $instigationStateId
    ) {
        __typename
        ... on InstigationState {
            ticks(limit: $limit, beforeTimestamp: $beforeTimestamp, afterTimestamp: $afterTimestamp) {
                id
                tickId
                status
                timestamp
                endTimestamp
                runIds
                runKeys
                originRunIds
                skipReason
                cursor
                instigationType
                requestedAssetMaterializationCount
                requestedAssetKeys { path }
                error { message }
            }
        }
        ... on InstigationStateNotFoundError { message }
        ... on PythonError { message }
    }
}"""

ASSET_NODES_QUERY = """
query AssetNodes($assetKeys: [AssetKeyInput!]) {
    assetNodes(assetKeys: $assetKeys) {
        id
        assetKey { path }
        groupName
        description
        computeKind
        opName
        opNames
        jobNames
        kinds
        isPartitioned
        isObservable
        isMaterializable
        isExecutable
        owners {
            __typename
            ... on UserAssetOwner { email }
            ... on TeamAssetOwner { team }
        }
        dependencyKeys { path }
        dependedByKeys { path }
        freshnessPolicy { maximumLagMinutes cronSchedule cronScheduleTimezone }
        autoMaterializePolicy { policyType maxMaterializationsPerMinute }
        partitionDefinition { description type name }
        tags { key value }
        repository { id name location { name } }
    }
}"""

# Only the scalar-valued members are unwrapped; every other entry still lands with its
# __typename and label so the row records that metadata was attached.
_METADATA_ENTRY_FRAGMENT = """
fragment MetadataEntryFields on MetadataEntry {
    __typename
    label
    description
    ... on TextMetadataEntry { text }
    ... on UrlMetadataEntry { url }
    ... on PathMetadataEntry { path }
    ... on IntMetadataEntry { intValue intRepr }
    ... on FloatMetadataEntry { floatValue }
    ... on BoolMetadataEntry { boolValue }
    ... on JsonMetadataEntry { jsonString }
    ... on MarkdownMetadataEntry { mdStr }
    ... on TimestampMetadataEntry { timestamp }
}"""

ASSET_MATERIALIZATIONS_QUERY = (
    """
query AssetMaterializations(
    $assetKeyPath: [String!]!
    $limit: Int!
    $beforeTimestampMillis: String
    $afterTimestampMillis: String
) {
    assetOrError(assetKey: { path: $assetKeyPath }) {
        __typename
        ... on Asset {
            assetMaterializations(
                limit: $limit
                beforeTimestampMillis: $beforeTimestampMillis
                afterTimestampMillis: $afterTimestampMillis
            ) {
                runId
                timestamp
                stepKey
                partition
                label
                description
                assetKey { path }
                tags { key value }
                metadataEntries { ...MetadataEntryFields }
            }
        }
        ... on AssetNotFoundError { message }
    }
}"""
    + _METADATA_ENTRY_FRAGMENT
)

ASSET_OBSERVATIONS_QUERY = (
    """
query AssetObservations(
    $assetKeyPath: [String!]!
    $limit: Int!
    $beforeTimestampMillis: String
    $afterTimestampMillis: String
) {
    assetOrError(assetKey: { path: $assetKeyPath }) {
        __typename
        ... on Asset {
            assetObservations(
                limit: $limit
                beforeTimestampMillis: $beforeTimestampMillis
                afterTimestampMillis: $afterTimestampMillis
            ) {
                runId
                timestamp
                stepKey
                partition
                label
                description
                assetKey { path }
                tags { key value }
                metadataEntries { ...MetadataEntryFields }
            }
        }
        ... on AssetNotFoundError { message }
    }
}"""
    + _METADATA_ENTRY_FRAGMENT
)

_DEPLOYMENT_FIELDS_FRAGMENT = """
fragment DeploymentFields on DagsterCloudDeployment {
    organizationId
    organizationName
    deploymentId
    deploymentName
    deploymentStatus
    deploymentType
    isBranchDeployment
    agentType
    parentDeployment { deploymentId deploymentName }
    branchDeploymentGitMetadata {
        branchName
        repoName
        branchUrl
        pullRequestUrl
        pullRequestStatus
        pullRequestNumber
    }
    latestCommit { timestamp commitHash commitMessage commitUrl authorName authorEmail }
}"""

# `deployments` returns only the subset the caller can reach, so the table is built from
# `fullDeployments` plus `branchDeployments` instead, because together they cover every deployment
# the organization has. Each row carries `isBranchDeployment` to tell the two apart.
DEPLOYMENTS_QUERY = (
    """
query Deployments($branchDeploymentLimit: Int!) {
    fullDeployments { ...DeploymentFields }
    branchDeployments(limit: $branchDeploymentLimit) {
        nodes { ...DeploymentFields }
    }
}"""
    + _DEPLOYMENT_FIELDS_FRAGMENT
)

# Every member of the DagsterRunEvent union implements MessageEvent, so the interface fragment
# alone gives every row its identity and timing; the rest add the step-timing markers and the
# error payload that make a failure readable.
RUN_LOGS_QUERY = """
query RunLogs($runId: ID!, $limit: Int!, $afterCursor: String) {
    logsForRun(runId: $runId, limit: $limit, afterCursor: $afterCursor) {
        __typename
        ... on EventConnection {
            cursor
            hasMore
            events {
                eventTypename: __typename
                ... on MessageEvent {
                    runId
                    message
                    timestamp
                    level
                    stepKey
                    solidHandleID
                    eventType
                }
                ... on RunEvent { pipelineName }
                ... on MarkerEvent { markerStart markerEnd }
                ... on ErrorEvent { error { message className } }
            }
        }
        ... on RunNotFoundError { message }
        ... on PythonError { message }
    }
}"""

_PERMISSION_GRANT_FRAGMENT = """
fragment PermissionGrantFields on DagsterCloudScopedPermissionGrant {
    id
    organizationId
    deploymentId
    grant
    customRoleId
    deploymentScope
    locationGrants { locationName grant customRoleId }
}"""

USERS_QUERY = (
    """
query OrganizationUsers {
    usersOrError {
        __typename
        ... on DagsterCloudUsersWithScopedPermissionGrants {
            users {
                id
                licensedRole
                user { id userId email name firstName lastName isScimProvisioned }
                organizationPermissionGrant { ...PermissionGrantFields }
                allBranchDeploymentsPermissionGrant { ...PermissionGrantFields }
                deploymentPermissionGrants { ...PermissionGrantFields }
            }
        }
        ... on UnauthorizedError { message }
        ... on PythonError { message }
    }
}"""
    + _PERMISSION_GRANT_FRAGMENT
)

TEAM_PERMISSIONS_QUERY = (
    """
query TeamPermissions {
    teamPermissions {
        id
        team { id name members { id userId email name } }
        organizationPermissionGrant { ...PermissionGrantFields }
        allBranchDeploymentsPermissionGrant { ...PermissionGrantFields }
        deploymentPermissionGrants { ...PermissionGrantFields }
    }
}"""
    + _PERMISSION_GRANT_FRAGMENT
)

CUSTOM_ROLES_QUERY = """
query CustomRoles {
    customRoles {
        id
        name
        description
        iconName
        permissions
        deploymentScope
    }
}"""


def _metric_types_query(operation: str, field: str) -> str:
    return f"""
query {operation} {{
    {field} {{
        __typename
        ... on MetricTypeList {{
            metricTypes {{ metricName displayName unitType category costMultiplier }}
        }}
        ... on UnauthorizedError {{ message }}
        ... on PythonError {{ message }}
    }}
}}"""


# reportingMetricsBy* takes one required metricName per request, so the sync reads the
# deployment's metric catalog first and walks it.
METRIC_TYPES_FOR_JOB_QUERY = _metric_types_query("MetricTypesForJob", "metricTypesForJob")
METRIC_TYPES_FOR_ASSET_QUERY = _metric_types_query("MetricTypesForAsset", "metricTypesForAsset")
METRIC_TYPES_FOR_DEPLOYMENT_QUERY = _metric_types_query("MetricTypesForDeployment", "metricTypesForDeployment")


def _reporting_metrics_query(operation: str, field: str, filter_type: str, entity_fragment: str) -> str:
    return f"""
query {operation}($metricsSelector: ReportingMetricsSelector!, $metricsFilter: {filter_type}) {{
    {field}(metricsSelector: $metricsSelector, metricsFilter: $metricsFilter) {{
        __typename
        ... on ReportingMetrics {{
            timestamps
            metrics {{
                values
                entity {{
                    __typename
                    {entity_fragment}
                }}
            }}
        }}
        ... on UnauthorizedError {{ message }}
        ... on ReportingInputError {{ message }}
        ... on PythonError {{ message }}
    }}
}}"""


REPORTING_METRICS_BY_JOB_QUERY = _reporting_metrics_query(
    "ReportingMetricsByJob",
    "reportingMetricsByJob",
    "JobReportingMetricsFilter",
    "... on ReportingJob { jobName codeLocationName repositoryName }",
)

REPORTING_METRICS_BY_ASSET_QUERY = _reporting_metrics_query(
    "ReportingMetricsByAsset",
    "reportingMetricsByAsset",
    "AssetReportingMetricsFilter",
    "... on ReportingAsset { assetKey { path } assetGroup codeLocationName repositoryName }",
)

REPORTING_METRICS_BY_DEPLOYMENT_QUERY = _reporting_metrics_query(
    "ReportingMetricsByDeployment",
    "reportingMetricsByDeployment",
    "DeploymentReportingMetricsFilter",
    "... on DagsterCloudDeployment { deploymentId deploymentName deploymentType isBranchDeployment }",
)
