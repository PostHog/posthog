import { createAccountAssignmentFilterUpdate, parseAccountAssignmentFilter } from './accountAssignmentFilter'

describe('accountAssignmentFilter', () => {
    it.each([
        ['new all status', { assignment_status: 'all' as const }, 'all'],
        ['new assigned status', { assignment_status: 'assigned' as const }, 'assigned'],
        ['new unassigned status', { assignment_status: 'unassigned' as const }, 'unassigned'],
        ['legacy empty filter', {}, 'all'],
        ['legacy assigned users', { assigned_to_user_ids: [7] }, 'assigned'],
        ['legacy unassigned filter', { all_roles_unassigned: true }, 'unassigned'],
    ])('parses %s', (_name, filters, expectedStatus) => {
        expect(parseAccountAssignmentFilter(filters).status).toBe(expectedStatus)
    })

    it.each([
        ['all', [7], { assignment_status: 'all', assigned_to_user_ids: [], all_roles_unassigned: undefined }],
        [
            'assigned',
            [7],
            { assignment_status: 'assigned', assigned_to_user_ids: [7], all_roles_unassigned: undefined },
        ],
        [
            'unassigned',
            [7],
            { assignment_status: 'unassigned', assigned_to_user_ids: [], all_roles_unassigned: undefined },
        ],
    ] as const)('creates a canonical %s update', (status, assignedToUserIds, expected) => {
        expect(createAccountAssignmentFilterUpdate(status, [...assignedToUserIds])).toEqual(expected)
    })
})
