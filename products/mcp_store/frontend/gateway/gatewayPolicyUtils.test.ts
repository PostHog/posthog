import { isPolicyStateAllowedByCeiling } from './gatewayPolicyUtils'

describe('isPolicyStateAllowedByCeiling', () => {
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
})
