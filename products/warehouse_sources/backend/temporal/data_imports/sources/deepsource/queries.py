# GraphQL queries for the DeepSource API (https://api.deepsource.com/graphql/).
# Field names verified against the live schema via introspection; DeepSource uses
# Relay-style connections (first/after + pageInfo.hasNextPage/endCursor) everywhere.

REPOSITORIES_QUERY = """
query Repositories($login: String!, $vcsProvider: VCSProvider!, $pageSize: Int!, $cursor: String) {
    account(login: $login, vcsProvider: $vcsProvider) {
        repositories(first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node {
                id
                name
                vcsProvider
                vcsUrl
                defaultBranch
                isPrivate
                isActivated
                latestCommitOid
            } }
        }
    }
}"""

# Cheap enumeration used to drive per-repository fan-out; only activated repositories
# have analysis data worth querying.
REPOSITORY_NAMES_QUERY = """
query RepositoryNames($login: String!, $vcsProvider: VCSProvider!, $pageSize: Int!, $cursor: String) {
    account(login: $login, vcsProvider: $vcsProvider) {
        repositories(first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node { name isActivated } }
        }
    }
}"""

ANALYSIS_RUNS_QUERY = """
query AnalysisRuns($login: String!, $vcsProvider: VCSProvider!, $name: String!, $pageSize: Int!, $cursor: String) {
    repository(login: $login, vcsProvider: $vcsProvider, name: $name) {
        id
        name
        analysisRuns(first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node {
                id
                runUid
                commitOid
                baseOid
                branchName
                status
                createdAt
                updatedAt
                finishedAt
                summary {
                    occurrencesIntroduced
                    occurrencesResolved
                    occurrencesSuppressed
                    vulnerabilitiesIntroduced
                }
            } }
        }
    }
}"""

ISSUES_QUERY = """
query RepositoryIssues($login: String!, $vcsProvider: VCSProvider!, $name: String!, $pageSize: Int!, $cursor: String) {
    repository(login: $login, vcsProvider: $vcsProvider, name: $name) {
        id
        name
        issues(first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node {
                id
                issue {
                    shortcode
                    title
                    category
                    severity
                    autofixAvailable
                    isRecommended
                    tags
                    analyzer { shortcode name }
                }
                occurrences { totalCount }
            } }
        }
    }
}"""

ISSUE_OCCURRENCES_QUERY = """
query IssueOccurrences($login: String!, $vcsProvider: VCSProvider!, $name: String!, $pageSize: Int!, $cursor: String) {
    repository(login: $login, vcsProvider: $vcsProvider, name: $name) {
        id
        name
        issueOccurrences(first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node {
                id
                path
                beginLine
                beginColumn
                endLine
                endColumn
                title
                issue {
                    shortcode
                    category
                    severity
                    analyzer { shortcode }
                }
            } }
        }
    }
}"""

VULNERABILITY_OCCURRENCES_QUERY = """
query VulnerabilityOccurrences($login: String!, $vcsProvider: VCSProvider!, $name: String!, $pageSize: Int!, $cursor: String) {
    repository(login: $login, vcsProvider: $vcsProvider, name: $name) {
        id
        name
        dependencyVulnerabilityOccurrences(first: $pageSize, after: $cursor) {
            pageInfo { hasNextPage endCursor }
            edges { node {
                id
                reachability
                fixability
                package { id name ecosystem purl }
                packageVersion { id version versionType }
                vulnerability {
                    id
                    identifier
                    severity
                    summary
                    publishedAt
                    updatedAt
                    withdrawnAt
                    cvssV2BaseScore
                    cvssV3BaseScore
                    cvssV4BaseScore
                    epssScore
                    epssPercentile
                    aliases
                    introducedVersions
                    fixedVersions
                    referenceUrls
                }
            } }
        }
    }
}"""

METRICS_QUERY = """
query RepositoryMetrics($login: String!, $vcsProvider: VCSProvider!, $name: String!) {
    repository(login: $login, vcsProvider: $vcsProvider, name: $name) {
        id
        name
        metrics {
            name
            shortcode
            description
            positiveDirection
            unit
            minValueAllowed
            maxValueAllowed
            isReported
            isThresholdEnforced
            items {
                id
                key
                threshold
                latestValue
                latestValueDisplay
                thresholdStatus
            }
        }
    }
}"""

# The security reports (owaspTop10, sansTop25, misraC) expose a status; the trend-style
# reports don't, so their rows carry status = null.
REPORTS_QUERY = """
query RepositoryReports($login: String!, $vcsProvider: VCSProvider!, $name: String!) {
    repository(login: $login, vcsProvider: $vcsProvider, name: $name) {
        id
        name
        reports {
            owaspTop10 { key title currentValue status }
            sansTop25 { key title currentValue status }
            misraC { key title currentValue status }
            codeHealthTrend { key title currentValue }
            issueDistribution { key title currentValue }
            issuesPrevented { key title currentValue }
            issuesAutofixed { key title currentValue }
        }
    }
}"""

# Create-time credential probe: `viewer` confirms the token is genuine, `account`
# confirms the configured login/provider is reachable with it.
VALIDATE_QUERY = """
query Validate($login: String!, $vcsProvider: VCSProvider!) {
    viewer { email }
    account(login: $login, vcsProvider: $vcsProvider) { id }
}"""

CONNECTION_QUERIES: dict[str, str] = {
    "analysis_runs": ANALYSIS_RUNS_QUERY,
    "issues": ISSUES_QUERY,
    "issue_occurrences": ISSUE_OCCURRENCES_QUERY,
    "vulnerability_occurrences": VULNERABILITY_OCCURRENCES_QUERY,
}

PER_REPOSITORY_QUERIES: dict[str, str] = {
    "metrics": METRICS_QUERY,
    "reports": REPORTS_QUERY,
}
