import {
    ErrorTrackingIssueAssignee,
    ErrorTrackingIssueStatus,
    ErrorTrackingPendingFingerprintIssueStateUpdate,
} from '~/queries/schema/schema-general'

export interface IssueStateDelta {
    status?: ErrorTrackingIssueStatus
    name?: string | null
    description?: string | null
    assignee?: ErrorTrackingIssueAssignee | null
}

export interface CurrentIssueState {
    id: string
    name: string | null
    description: string | null
    status: ErrorTrackingIssueStatus
    assignee: ErrorTrackingIssueAssignee | null
    first_seen: string
}

export function applyDelta(current: CurrentIssueState, delta: IssueStateDelta): CurrentIssueState {
    return {
        ...current,
        status: delta.status ?? current.status,
        name: delta.name !== undefined ? delta.name : current.name,
        description: delta.description !== undefined ? delta.description : current.description,
        assignee: delta.assignee !== undefined ? delta.assignee : current.assignee,
    }
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
        assigned_user_id: assignee?.type === 'user' ? Number(assignee.id) : null,
        assigned_role_id: assignee?.type === 'role' ? String(assignee.id) : null,
        first_seen: state.first_seen,
        is_deleted: 0,
        version,
    }
}
