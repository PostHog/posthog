import type { ReportView } from '@/model/types'

/** The full report adds the summary and the signals, so without either it has nothing the report screen lacks. */
export function hasReportDetail(report: Pick<ReportView, 'summary' | 'signals'>): boolean {
    return Boolean(report.summary) || report.signals.length > 0
}
