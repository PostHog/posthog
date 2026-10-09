import type { SignalReportApi } from '@/api/reports'
import type { BriefingApi, BriefingItemApi } from '@/api/today'

import { POSTHOG_AGENT } from '../agent'
import { isErrorSource, isFeedbackSource, primarySource, sourceInfo, toSourceProduct } from '../sources'
import type { Accent, InboxItem, InboxItemState, InboxReason, SourceProduct } from '../types'

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

const ITEM_SOURCES: Record<string, SourceProduct> = {
    error_tracking: 'error_tracking',
    github: 'github',
    product_analytics: 'analytics',
    support: 'conversations',
    self_driving: 'signals_scout',
}

const REASONS: ReadonlySet<string> = new Set<InboxReason>([
    'claimed_by_you',
    'waiting_for_you',
    'suggested_reviewer',
    'urgent_for_project',
    'review_requested',
    'your_pull_request',
])

function toReason(value: string): InboxReason {
    return REASONS.has(value) ? (value as InboxReason) : 'other'
}

const REPORT_KEY_PREFIX = 'report:'

export function briefingReportId(item: Pick<BriefingItemApi, 'key'>): string | null {
    return item.key.startsWith(REPORT_KEY_PREFIX) ? item.key.slice(REPORT_KEY_PREFIX.length) : null
}

function itemAccent(item: BriefingItemApi): Accent {
    if (item.state === 'done' || item.state === 'dismissed') {
        return 'resolved'
    }
    return accentFor(item.source_product ? [item.source_product] : [])
}

// The briefing does not say who claimed a report, so rows carry no agent badge.
export function inboxFromBriefing(briefing: BriefingApi): InboxItem[] {
    const items: InboxItem[] = []
    for (const item of [...briefing.items].sort((a, b) => a.rank - b.rank)) {
        const reportId = briefingReportId(item)
        if (item.group !== 'report' || !reportId || !item.report) {
            continue
        }
        const sourceProduct = item.source_product
            ? toSourceProduct(item.source_product)
            : (ITEM_SOURCES[item.source] ?? 'other')
        items.push({
            id: item.key,
            reportId,
            title: item.title,
            sourceProduct,
            sourceLabel: sourceInfo(sourceProduct).label,
            accent: itemAccent(item),
            updatedAt: item.report.updated_at,
            rank: item.rank,
            reason: toReason(item.reason),
            state: item.state,
            needsInput: item.reason === 'waiting_for_you',
            read: false,
        })
    }
    return items
}

function reportItemState(status: string): InboxItemState {
    if (status === 'resolved') {
        return 'done'
    }
    return CLOSED_STATUSES.has(status) ? 'dismissed' : 'open'
}

export function inboxFromReports(reports: readonly SignalReportApi[]): InboxItem[] {
    return reports.map((report) => {
        const sourceProduct = primarySource(report.source_products)
        const agentClaimed = report.assignee?.kind === 'task' || report.assignee?.kind === 'agent'
        const needsInput = report.status === 'pending_input'
        return {
            id: report.id,
            reportId: report.id,
            title: report.title?.trim() || 'Untitled report',
            sourceProduct,
            sourceLabel: sourceInfo(sourceProduct).label,
            accent: accentFor(report.source_products, report.status),
            updatedAt: report.updated_at,
            reason: needsInput ? 'waiting_for_you' : report.is_suggested_reviewer ? 'suggested_reviewer' : 'other',
            state: reportItemState(report.status),
            needsInput,
            read: false,
            ...(agentClaimed ? { agent: { ...POSTHOG_AGENT } } : {}),
        }
    })
}

export function signalCountsFromBriefing(briefing: BriefingApi): Record<string, number> {
    const counts: Record<string, number> = {}
    for (const item of briefing.items) {
        const reportId = briefingReportId(item)
        if (reportId && item.report) {
            counts[reportId] = item.report.signal_count
        }
    }
    return counts
}

export function signalCountsFromReports(reports: readonly SignalReportApi[]): Record<string, number> {
    return Object.fromEntries(reports.map((report) => [report.id, report.signal_count]))
}
