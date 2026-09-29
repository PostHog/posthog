import {
    type AssignmentStatus,
    isAssignmentStatus,
} from 'lib/components/AccountAssignmentFilter/accountAssignmentFilterTypes'

export interface WorkflowAccountAssignmentFilters {
    assignment_status?: AssignmentStatus
    assigned_to_user_ids?: number[]
    all_roles_unassigned?: boolean
}

export interface WorkflowAccountAssignmentFilterValue {
    status: AssignmentStatus
    assignedToUserIds: number[]
}

export function parseAccountAssignmentFilter(
    filters: WorkflowAccountAssignmentFilters
): WorkflowAccountAssignmentFilterValue {
    const assignedToUserIds = filters.assigned_to_user_ids ?? []
    // Infer the status without rewriting workflows saved before assignment_status existed.
    const status = isAssignmentStatus(filters.assignment_status)
        ? filters.assignment_status
        : filters.all_roles_unassigned
          ? 'unassigned'
          : assignedToUserIds.length > 0
            ? 'assigned'
            : 'all'

    return { status, assignedToUserIds }
}

export function createAccountAssignmentFilterUpdate(
    status: AssignmentStatus,
    assignedToUserIds: number[]
): WorkflowAccountAssignmentFilters {
    // New edits remove the legacy flag so it cannot conflict with the canonical status.
    return {
        assignment_status: status,
        assigned_to_user_ids: status === 'assigned' ? assignedToUserIds : [],
        all_roles_unassigned: undefined,
    }
}
