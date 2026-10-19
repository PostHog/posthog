import type { InboxPageApi, SignalReportApi } from '@/api/reports'

import { POSTHOG_AGENT } from '../agent'
import { isErrorSource, isFeedbackSource, primarySource, sourceInfo } from '../sources'
import type { Accent, InboxItem, InboxItemState } from '../types'
import { primaryPullRequestState, primaryPullRequestUrl } from './report'
import { displayTitle } from './text'

const CLOSED_STATUSES: ReadonlySet<string> = new Set(['resolved', 'suppressed', 'deleted'])

export function accentFor(sources: readonly string[], status?: string): Accent {
    if (status && CLOSED_STATUSES.has(status)) {
        return 'resolved'
    }
    if (sources.length === 0 || sources.some(isErrorSource)) {
        return 'alert'
    }
    const feedbackLike = sources.every((source) => isFeedbackSource(source) || source === 'signals_scout')
    return feedbackLike ? 'opportunity' : 'alert'
}

function reportItemState(status: string): InboxItemState {
    if (status === 'resolved') {
        return 'done'
    }
    return CLOSED_STATUSES.has(status) ? 'dismissed' : 'open'
}

// Each page ranks the reports again, so a report that moved up can come back on a later page.
export function reportsFromPages(pages: readonly InboxPageApi[]): SignalReportApi[] {
    const seen = new Set<string>()
    const reports: SignalReportApi[] = []
    for (const report of pages.flatMap((page) => page.results)) {
        if (!seen.has(report.id)) {
            seen.add(report.id)
            reports.push(report)
        }
    }
    return reports
}

export function inboxFromReports(reports: readonly SignalReportApi[]): InboxItem[] {
    return reports.map((report) => {
        const sourceProduct = primarySource(report.source_products)
        const agentClaimed = report.assignee?.kind === 'task' || report.assignee?.kind === 'agent'
        const needsInput = report.status === 'pending_input'
        const pullRequestUrl = primaryPullRequestUrl(report)
        const pullRequestState = primaryPullRequestState(report)
        return {
            id: report.id,
            reportId: report.id,
            title: displayTitle(report.title, 'Untitled report'),
            sourceProduct,
            sourceLabel: sourceInfo(sourceProduct).label,
            sources: report.source_products,
            accent: accentFor(report.source_products, report.status),
            createdAt: report.created_at,
            updatedAt: report.updated_at,
            modelScore: report.ranking?.scores?.pr_merged ?? null,
            reason: needsInput ? 'waiting_for_you' : report.is_suggested_reviewer ? 'suggested_reviewer' : 'other',
            state: reportItemState(report.status),
            needsInput,
            read: false,
            ...(agentClaimed ? { agent: { ...POSTHOG_AGENT } } : {}),
            ...(pullRequestUrl ? { pullRequestUrl } : {}),
            ...(pullRequestState ? { pullRequestState } : {}),
        }
    })
}

export function signalCountsFromReports(reports: readonly SignalReportApi[]): Record<string, number> {
    return Object.fromEntries(reports.map((report) => [report.id, report.signal_count]))
}
