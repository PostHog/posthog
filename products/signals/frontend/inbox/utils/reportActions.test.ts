import { SignalReport, SignalReportStatus } from '../types'
import { canMonitorReport, canResolveReport } from './reportActions'

describe('canResolveReport', () => {
    it.each([
        [SignalReportStatus.READY, true],
        [SignalReportStatus.PENDING_INPUT, true],
        [SignalReportStatus.FAILED, true],
        [SignalReportStatus.MONITORING, true],
        [SignalReportStatus.POTENTIAL, false],
        [SignalReportStatus.CANDIDATE, false],
        [SignalReportStatus.IN_PROGRESS, false],
        [SignalReportStatus.RESOLVED, false],
        [SignalReportStatus.SUPPRESSED, false],
    ] as const)('allows resolution for %s: %s', (status, expected) => {
        expect(canResolveReport({ status } as SignalReport)).toBe(expected)
    })

    it.each([
        [SignalReportStatus.READY, true, true],
        [SignalReportStatus.READY, false, false],
        [SignalReportStatus.PENDING_INPUT, true, true],
        [SignalReportStatus.FAILED, true, true],
        [SignalReportStatus.MONITORING, true, false],
        [SignalReportStatus.RESOLVED, true, false],
        [SignalReportStatus.SUPPRESSED, true, false],
    ] as const)('gates manual Monitoring for %s with server capability %s: %s', (status, enabled, expected) => {
        expect(
            canMonitorReport({ status, ...(enabled ? { monitoring_started_at: null } : {}) } as SignalReport, true)
        ).toBe(expected)
    })

    it.each([false, true])('offers Monitoring only with follow-up checks: %s', (hasFollowUpChecks) => {
        expect(
            canMonitorReport(
                { status: SignalReportStatus.READY, monitoring_started_at: null } as SignalReport,
                hasFollowUpChecks
            )
        ).toBe(hasFollowUpChecks)
    })
})
