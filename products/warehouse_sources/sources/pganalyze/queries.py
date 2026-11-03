# Matches the public GraphQL schema documented at https://pganalyze.com/docs/api/queries
SERVERS_QUERY = """
query GetServers($organizationSlug: ID!) {
    getServers(organizationSlug: $organizationSlug) {
        id
        humanId
        name
        systemType
        systemScope
        systemId
        lastSnapshotAt
    }
}
"""

ISSUES_QUERY = """
query GetIssues($serverId: ID) {
    getIssues(serverId: $serverId) {
        id
        databaseId
        description
        severity
        references {
            kind
            name
            url
            queryText
        }
    }
}
"""

# pganalyze documents no query that lists databases, so we collect database ids from the issues of each server.
ISSUE_DATABASE_IDS_QUERY = """
query GetIssueDatabaseIds($serverId: ID) {
    getIssues(serverId: $serverId) {
        databaseId
    }
}
"""

QUERY_STATS_QUERY = """
query GetQueryStats($databaseId: ID!, $startTs: Int, $endTs: Int) {
    getQueryStats(databaseId: $databaseId, startTs: $startTs, endTs: $endTs) {
        id
        queryUrl
        normalizedQuery
        truncatedQuery
        queryComment
        statementTypes
        totalCalls
        avgTime
        avgIoTime
        bufferHitRatio
        pctOfTotal
    }
}
"""
