import { defaultAgentGrantPolicy, isPolicyStateAllowedByCeiling } from './gatewayPolicyUtils'

describe('gatewayPolicyUtils', () => {
    it.each([
        ['approved', 'needs_approval', false],
        ['needs_approval', 'needs_approval', true],
        ['do_not_use', 'needs_approval', true],
        ['approved', 'do_not_use', false],
        ['needs_approval', 'do_not_use', false],
        ['do_not_use', 'do_not_use', true],
        ['approved', 'approved', true],
        ['approved', null, true],
    ] as const)('%s under a %s ceiling is %s', (state, ceiling, expected) => {
        expect(isPolicyStateAllowedByCeiling(state, ceiling)).toBe(expected)
    })

    it.each([
        ['delete_issue', null, 'do_not_use'],
        ['remove_user', null, 'do_not_use'],
        ['destroy_project', null, 'do_not_use'],
        ['purge_data', null, 'do_not_use'],
        ['DeleteProject', null, 'do_not_use'],
        ['list_issues', null, 'approved'],
        ['list_issues', 'needs_approval', 'do_not_use'],
    ] as const)('defaults %s under a %s team policy to %s', (toolName, teamState, expected) => {
        expect(defaultAgentGrantPolicy(toolName, teamState)).toBe(expected)
    })

    it('uses the canonical destructive classification returned by the gateway', () => {
        expect(defaultAgentGrantPolicy('manage_project', null, true)).toBe('do_not_use')
        expect(defaultAgentGrantPolicy('delete_project', null, false)).toBe('approved')
    })
})
