ISSUES_QUERY = """
query PaginatedIssues($pageSize: Int!, $cursor: String, $filter: IssueFilter) {
    issues(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            identifier
            title
            description
            priority
            priorityLabel
            estimate
            createdAt
            updatedAt
            completedAt
            canceledAt
            archivedAt
            startedAt
            dueDate
            sortOrder
            number
            url
            assignee { id name email }
            state { id name type color }
            team { id name key }
            labels { nodes { id name color } }
            project { id name }
            cycle { id name number }
            creator { id name email }
            parent { id identifier }
            relations(first: 10) { nodes { id type relatedIssue { id identifier } } }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

PROJECTS_QUERY = """
query PaginatedProjects($pageSize: Int!, $cursor: String, $filter: ProjectFilter) {
    projects(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            description
            state
            progress
            createdAt
            updatedAt
            completedAt
            canceledAt
            startedAt
            targetDate
            startDate
            slugId
            icon
            color
            url
            lead { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

TEAMS_QUERY = """
query PaginatedTeams($pageSize: Int!, $cursor: String) {
    teams(first: $pageSize, after: $cursor) {
        nodes {
            id
            name
            key
            description
            icon
            color
            createdAt
            updatedAt
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

USERS_QUERY = """
query PaginatedUsers($pageSize: Int!, $cursor: String) {
    users(first: $pageSize, after: $cursor) {
        nodes {
            id
            name
            displayName
            email
            active
            admin
            createdAt
            updatedAt
            isMe
            avatarUrl
            url
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

COMMENTS_QUERY = """
query PaginatedComments($pageSize: Int!, $cursor: String, $filter: CommentFilter) {
    comments(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            body
            createdAt
            updatedAt
            url
            issue { id identifier }
            user { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

LABELS_QUERY = """
query PaginatedLabels($pageSize: Int!, $cursor: String) {
    issueLabels(first: $pageSize, after: $cursor) {
        nodes {
            id
            name
            description
            color
            createdAt
            updatedAt
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

CYCLES_QUERY = """
query PaginatedCycles($pageSize: Int!, $cursor: String, $filter: CycleFilter) {
    cycles(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            number
            description
            startsAt
            endsAt
            completedAt
            createdAt
            updatedAt
            progress
            scopeHistory
            completedScopeHistory
            team { id name }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

RESOURCES_QUERY = """
query PaginatedAttachments($pageSize: Int!, $cursor: String, $filter: AttachmentFilter) {
    attachments(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            title
            url
            subtitle
            sourceType
            createdAt
            updatedAt
            issue { id identifier }
            creator { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

WORKFLOW_STATES_QUERY = """
query PaginatedWorkflowStates($pageSize: Int!, $cursor: String, $filter: WorkflowStateFilter) {
    workflowStates(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            type
            color
            description
            position
            createdAt
            updatedAt
            archivedAt
            team { id name key }
            inheritedFrom { id name }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

PROJECT_MILESTONES_QUERY = """
query PaginatedProjectMilestones($pageSize: Int!, $cursor: String, $filter: ProjectMilestoneFilter) {
    projectMilestones(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            description
            status
            progress
            sortOrder
            targetDate
            createdAt
            updatedAt
            archivedAt
            project { id name }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

INITIATIVES_QUERY = """
query PaginatedInitiatives($pageSize: Int!, $cursor: String, $filter: InitiativeFilter) {
    initiatives(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            name
            description
            content
            slugId
            status
            health
            priority
            sortOrder
            icon
            color
            url
            targetDate
            targetDateResolution
            startedAt
            completedAt
            healthUpdatedAt
            trashed
            createdAt
            updatedAt
            archivedAt
            creator { id name email }
            owner { id name email }
            parentInitiative { id name }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

TEAM_MEMBERSHIPS_QUERY = """
query PaginatedTeamMemberships($pageSize: Int!, $cursor: String) {
    teamMemberships(first: $pageSize, after: $cursor) {
        nodes {
            id
            owner
            sortOrder
            createdAt
            updatedAt
            archivedAt
            team { id name key }
            user { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

ISSUE_RELATIONS_QUERY = """
query PaginatedIssueRelations($pageSize: Int!, $cursor: String) {
    issueRelations(first: $pageSize, after: $cursor) {
        nodes {
            id
            type
            createdAt
            updatedAt
            archivedAt
            issue { id identifier }
            relatedIssue { id identifier }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

PROJECT_UPDATES_QUERY = """
query PaginatedProjectUpdates($pageSize: Int!, $cursor: String, $filter: ProjectUpdateFilter) {
    projectUpdates(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            body
            health
            url
            slugId
            commentCount
            isStale
            isDiffHidden
            diffMarkdown
            editedAt
            createdAt
            updatedAt
            archivedAt
            project { id name }
            user { id name email }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

DOCUMENTS_QUERY = """
query PaginatedDocuments($pageSize: Int!, $cursor: String, $filter: DocumentFilter) {
    documents(first: $pageSize, after: $cursor, orderBy: updatedAt, filter: $filter) {
        nodes {
            id
            title
            content
            icon
            color
            slugId
            url
            trashed
            hiddenAt
            createdAt
            updatedAt
            archivedAt
            creator { id name email }
            updatedBy { id name email }
            project { id name }
            initiative { id name }
            issue { id identifier }
        }
        pageInfo { hasNextPage endCursor }
    }
}"""

VIEWER_QUERY = "{ viewer { id } }"

QUERIES: dict[str, str] = {
    "issues": ISSUES_QUERY,
    "projects": PROJECTS_QUERY,
    "teams": TEAMS_QUERY,
    "users": USERS_QUERY,
    "comments": COMMENTS_QUERY,
    "labels": LABELS_QUERY,
    "cycles": CYCLES_QUERY,
    "resources": RESOURCES_QUERY,
    "workflow_states": WORKFLOW_STATES_QUERY,
    "project_milestones": PROJECT_MILESTONES_QUERY,
    "initiatives": INITIATIVES_QUERY,
    "team_memberships": TEAM_MEMBERSHIPS_QUERY,
    "issue_relations": ISSUE_RELATIONS_QUERY,
    "project_updates": PROJECT_UPDATES_QUERY,
    "documents": DOCUMENTS_QUERY,
}
