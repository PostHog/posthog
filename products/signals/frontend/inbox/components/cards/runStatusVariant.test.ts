import { SignalReportStatus } from '../../types'
import { resolveRunVariant } from './runStatusVariant'

describe('resolveRunVariant', () => {
    it.each([
        [SignalReportStatus.MONITORING, 'completed'],
        [SignalReportStatus.CLOSED, 'completed'],
        [SignalReportStatus.POTENTIAL, 'queued'],
        [SignalReportStatus.CANDIDATE, 'queued'],
        ['not_started', 'queued'],
        ['queued', 'queued'],
        ['completed', 'completed'],
        ['cancelled', 'failed'],
        [null, 'queued'],
        [undefined, 'queued'],
    ] as const)('shows %s as %s', (status, expected) => {
        expect(resolveRunVariant(status)).toBe(expected)
    })
})
