import { SignalReport, SignalReportStatus } from '../types'
import { canResolveReport } from './reportActions'

describe('canResolveReport', () => {
    it.each([
        [SignalReportStatus.READY, true],
        [SignalReportStatus.PENDING_INPUT, true],
        [SignalReportStatus.FAILED, true],
        [SignalReportStatus.POTENTIAL, false],
        [SignalReportStatus.CANDIDATE, false],
        [SignalReportStatus.IN_PROGRESS, false],
        [SignalReportStatus.RESOLVED, false],
        [SignalReportStatus.SUPPRESSED, false],
    ] as const)('allows resolution for %s: %s', (status, expected) => {
        expect(canResolveReport({ status } as SignalReport)).toBe(expected)
    })
})
