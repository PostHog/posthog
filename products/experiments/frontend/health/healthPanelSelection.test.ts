import type { HealthPanelFinding } from './healthPanelFindings'
import { resolveHealthPanelSelection } from './healthPanelSelection'

const ISSUE: HealthPanelFinding = {
    code: 'srm',
    subcode: null,
    reason: null,
    severity: 'warning',
    title: 'Users are not split as configured',
    detail: '',
    evidence: {},
    actions: [],
}

describe('resolveHealthPanelSelection', () => {
    it.each([
        { name: 'opens the overview without a pick, even with an issue', picked: null, expected: 'overview' },
        {
            name: 'keeps the issue that the reader picked',
            picked: { kind: 'finding', key: 'srm:' },
            expected: 'finding',
        },
        {
            name: 'falls back to the overview when the picked issue is gone',
            picked: { kind: 'finding', key: 'zero_exposures:' },
            expected: 'overview',
        },
    ] as const)('$name', ({ picked, expected }) => {
        expect(resolveHealthPanelSelection(picked, [ISSUE], []).kind).toEqual(expected)
    })
})
