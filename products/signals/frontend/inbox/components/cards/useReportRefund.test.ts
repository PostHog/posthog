import { SignalReport, SignalReportStatus } from '../../types'
import { refundKeptStatus } from './useReportRefund'

describe('refundKeptStatus', () => {
    const report = (status: SignalReportStatus, merged: boolean): SignalReport =>
        ({
            id: 'report-1',
            status,
            implementation_pr_url: 'https://github.com/example/app/pull/1',
            implementation_pr_merged: merged,
        }) as unknown as SignalReport

    it.each([
        [SignalReportStatus.MONITORING, true, SignalReportStatus.MONITORING],
        [SignalReportStatus.RESOLVED, true, SignalReportStatus.RESOLVED],
        [SignalReportStatus.MONITORING, false, null],
        [SignalReportStatus.READY, true, null],
    ])('keeps a %s report with merged=%s as %s', (status, merged, expected) => {
        expect(refundKeptStatus(report(status, merged))).toBe(expected)
    })
})
