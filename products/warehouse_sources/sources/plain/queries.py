CUSTOMERS_QUERY = """
query PaginatedCustomers($first: Int!, $after: String, $filter: CustomersFilter) {
    customers(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
                externalId
                fullName
                shortName
                email {
                    email
                    isVerified
                }
                status
                statusChangedAt {
                    iso8601
                }
                assignedToUser {
                    user {
                        id
                        fullName
                        email
                    }
                }
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                markedAsSpamAt {
                    iso8601
                }
                markedAsSpamBy {
                    actorType: __typename
                    ... on UserActor { userId }
                }
                company {
                    id
                    name
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

THREADS_QUERY = """
query PaginatedThreads($first: Int!, $after: String, $filter: ThreadsFilter) {
    threads(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
                externalId
                customer {
                    id
                    fullName
                    email {
                        email
                    }
                }
                title
                previewText
                priority
                status
                statusChangedAt {
                    iso8601
                }
                statusChangedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                assignedToUser: assignedTo {
                    __typename
                    ... on User {
                        id
                        fullName
                        email
                    }
                    ... on MachineUser {
                        id
                        fullName
                    }
                    ... on System {
                        id
                    }
                }
                labels {
                    id
                    labelType {
                        id
                        name
                    }
                }
                firstInboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                firstOutboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                lastInboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                lastOutboundMessageInfo {
                    timestamp {
                        iso8601
                    }
                }
                supportEmailAddresses
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

TIMELINE_ENTRIES_QUERY = """
query ThreadTimelineEntries($threadId: ID!, $first: Int!, $after: String) {
    thread(threadId: $threadId) {
        timelineEntries(first: $first, after: $after) {
            edges {
                node {
                    id
                    timestamp {
                        iso8601
                    }
                    actor {
                        actorType: __typename
                        ... on UserActor { userId }
                        ... on MachineUserActor { machineUserId }
                        ... on CustomerActor { customerId }
                        ... on SystemActor { systemId }
                    }
                    entry {
                        __typename
                        ... on ChatEntry {
                            chatId
                            text
                        }
                        ... on EmailEntry {
                            emailId
                            subject
                            textContent
                            to {
                                email
                                name
                            }
                            from {
                                email
                                name
                            }
                        }
                        ... on NoteEntry {
                            noteId
                            noteText: text
                        }
                        ... on CustomEntry {
                            title
                            externalId
                        }
                    }
                }
            }
            pageInfo {
                hasNextPage
                endCursor
            }
        }
    }
}"""

THREADS_LIST_QUERY = """
query ThreadIdsList($first: Int!, $after: String, $filter: ThreadsFilter) {
    threads(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

COMPANIES_QUERY = """
query PaginatedCompanies($first: Int!, $after: String, $filter: CompaniesFilter) {
    companies(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
                name
                domainName
                logoUrl
                contractValue
                accountOwner {
                    id
                }
                isDeleted
                deletedAt {
                    iso8601
                }
                deletedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

USERS_QUERY = """
query PaginatedUsers($first: Int!, $after: String) {
    users(first: $first, after: $after) {
        edges {
            node {
                id
                fullName
                publicName
                email
                avatarUrl
                status
                statusChangedAt {
                    iso8601
                }
                isDeleted
                deletedAt {
                    iso8601
                }
                deletedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                isManagedByDirectory
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

LABEL_TYPES_QUERY = """
query PaginatedLabelTypes($first: Int!, $after: String) {
    label_types: labelTypes(first: $first, after: $after) {
        edges {
            node {
                id
                name
                type
                description
                icon
                color
                position
                externalId
                parentLabelType {
                    id
                }
                isArchived
                archivedAt {
                    iso8601
                }
                archivedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                isExcludedFromAi
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

TENANTS_QUERY = """
query PaginatedTenants($first: Int!, $after: String, $filter: TenantsFilter) {
    tenants(first: $first, after: $after, filters: $filter) {
        edges {
            node {
                id
                name
                externalId
                url
                source
                primaryDomain
                alternateDomains
                logoUrl
                isDomainAutoJoinEnabled
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

CUSTOMER_GROUPS_QUERY = """
query PaginatedCustomerGroups($first: Int!, $after: String) {
    customer_groups: customerGroups(first: $first, after: $after) {
        edges {
            node {
                id
                name
                key
                color
                externalId
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

CUSTOMER_SURVEYS_QUERY = """
query PaginatedCustomerSurveys($first: Int!, $after: String) {
    customer_surveys: customerSurveys(first: $first, after: $after) {
        edges {
            node {
                id
                name
                template {
                    ... on CsatCustomerSurveyTemplate {
                        type
                        questionText
                    }
                }
                conditionsOperator
                isEnabled
                responseDelayMinutes
                customerIntervalDays
                order
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

DISCUSSIONS_QUERY = """
query PaginatedDiscussions($first: Int!, $after: String) {
    discussions(first: $first, after: $after, sortBy: { field: CREATED_AT, direction: ASC }) {
        edges {
            node {
                id
                threadId
                title
                status
                agentStatus
                agent {
                    id
                }
                agentSessionId
                channelDetails {
                    channelType: __typename
                }
                visibility
                sourceType
                sourceEntityId
                sourceEntityType
                sourcePageLink
                resolvedAt {
                    iso8601
                }
                lastActivityAt {
                    iso8601
                }
                createdAt {
                    iso8601
                }
                createdBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on CustomerActor { customerId }
                    ... on DeletedCustomerActor { customerId }
                    ... on SystemActor { systemId }
                }
                updatedAt {
                    iso8601
                }
                updatedBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on CustomerActor { customerId }
                    ... on DeletedCustomerActor { customerId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

# `workflowExecutions` needs a workflowId; the workspace-wide query lists every workflow's runs in one walk.
WORKFLOW_EXECUTIONS_QUERY = """
query PaginatedWorkflowExecutions($first: Int!, $after: String) {
    workflow_executions: workflowExecutionsForWorkspace(first: $first, after: $after) {
        edges {
            node {
                id
                workflowId
                triggeredBy
                executionStatus
                errorMessage
                entityType
                entityId
                startedAt {
                    iso8601
                }
                completedAt {
                    iso8601
                }
                executionDurationMs
                manuallyTriggeredBy {
                    actorType: __typename
                    ... on UserActor { userId }
                    ... on MachineUserActor { machineUserId }
                    ... on SystemActor { systemId }
                }
            }
        }
        pageInfo {
            hasNextPage
            endCursor
        }
    }
}"""

VIEWER_QUERY = "{ myWorkspace { id name } }"

QUERIES: dict[str, str] = {
    "customers": CUSTOMERS_QUERY,
    "threads": THREADS_QUERY,
    "timeline_entries": TIMELINE_ENTRIES_QUERY,
    "companies": COMPANIES_QUERY,
    "tenants": TENANTS_QUERY,
    "users": USERS_QUERY,
    "label_types": LABEL_TYPES_QUERY,
    "customer_groups": CUSTOMER_GROUPS_QUERY,
    "customer_surveys": CUSTOMER_SURVEYS_QUERY,
    "discussions": DISCUSSIONS_QUERY,
    "workflow_executions": WORKFLOW_EXECUTIONS_QUERY,
}
