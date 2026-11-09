import { SignalReportStatus } from '../../types'
import { resolveRunVariant } from './runStatusVariant'

describe('resolveRunVariant', () => {
    it.each([
        [SignalReportStatus.MONITORING, 'completed'],
        [SignalReportStatus.CLOSED, 'completed'],
        [SignalReportStatus.POTENTIAL, 'queued'],
        [SignalReportStatus.CANDIDATE, 'queued'],
        [SignalReportStatus.IN_PROGRESS, 'live'],
        [SignalReportStatus.PENDING_INPUT, 'live'],
        [SignalReportStatus.READY, 'completed'],
        [SignalReportStatus.RESOLVED, 'completed'],
        [SignalReportStatus.FAILED, 'failed'],
        [SignalReportStatus.SUPPRESSED, 'completed'],
        [SignalReportStatus.DELETED, 'completed'],
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
