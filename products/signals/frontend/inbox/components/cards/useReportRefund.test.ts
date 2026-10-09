import { SignalReport, SignalReportStatus } from '../../types'
import { refundKeptStatus } from './useReportRefund'

describe('refundKeptStatus', () => {
    const report = (status: SignalReportStatus, keptStatus: SignalReport['refund_kept_status']): SignalReport =>
        ({
            id: 'report-1',
            status,
            implementation_pr_url: 'https://github.com/example/app/pull/1',
            implementation_pr_merged: true,
            refund_kept_status: keptStatus,
        }) as unknown as SignalReport

    it.each([
        [SignalReportStatus.MONITORING, 'monitoring', SignalReportStatus.MONITORING],
        [SignalReportStatus.RESOLVED, 'resolved', SignalReportStatus.RESOLVED],
        [SignalReportStatus.MONITORING, null, null],
        [SignalReportStatus.RESOLVED, null, null],
        [SignalReportStatus.READY, null, null],
    ] as const)('uses the backend retained status for %s with a merged PR', (status, keptStatus, expected) => {
        expect(refundKeptStatus(report(status, keptStatus))).toBe(expected)
    })
})
