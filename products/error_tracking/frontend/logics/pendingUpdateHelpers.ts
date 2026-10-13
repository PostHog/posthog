import {
    ErrorTrackingIssueAssignee,
    ErrorTrackingIssueStatus,
    ErrorTrackingQueryIssueSeverity,
    ErrorTrackingPendingFingerprintIssueStateUpdate,
} from '~/queries/schema/schema-general'

export interface CurrentIssueState {
    id: string
    name: string | null
    description: string | null
    status: ErrorTrackingIssueStatus
    severity: ErrorTrackingQueryIssueSeverity | null
    assignee: ErrorTrackingIssueAssignee | null
    first_seen: string
}

export function buildPendingUpdate(
    fingerprint: string,
    issueId: string,
    state: CurrentIssueState,
    version: number
): ErrorTrackingPendingFingerprintIssueStateUpdate {
    const assignee = state.assignee
    return {
        fingerprint,
        issue_id: issueId,
        issue_name: state.name ?? null,
        issue_description: state.description ?? null,
        issue_status: state.status,
        issue_severity: state.severity,
        assigned_user_id: assignee?.type === 'user' ? Number(assignee.id) : null,
        assigned_role_id: assignee?.type === 'role' ? String(assignee.id) : null,
        first_seen: state.first_seen,
        is_deleted: 0,
        version,
    }
}
