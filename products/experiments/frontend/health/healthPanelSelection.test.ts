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
        { name: 'opens the first issue without a pick', picked: null, expected: 'finding' },
        {
            name: 'keeps the summary that the reader picked over an issue',
            picked: { kind: 'summary' },
            expected: 'summary',
        },
    ] as const)('$name', ({ picked, expected }) => {
        expect(resolveHealthPanelSelection(picked, [ISSUE], []).kind).toEqual(expected)
    })
})
