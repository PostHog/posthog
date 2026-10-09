import { apiJson, projectPath } from './client'

// Shapes follow `products/today/backend/presentation/serializers.py`. Both endpoints return 404 when the project or
// person has no Today (flag off, no AI data processing approval, no AI credits); callers fall back to signals reports.

export type BriefingStatusApi = 'collecting' | 'writing' | 'ready' | 'failed'

export interface BriefingItemReportApi {
    priority: string | null
    pull_request_state: string | null
    signal_count: number
    updated_at: string
}

export interface BriefingItemApi {
    /** `report:<uuid>`, `dashboard:<id>`, `ticket:<uuid>`, ... */
    key: string
    group: 'report' | 'dashboard' | 'other'
    source: string
    reason: string
    title: string
    rank: number
    state: 'open' | 'done' | 'dismissed' | 'left'
    source_product: string | null
    /** Null for items that are not reports and for deleted reports. */
    report: BriefingItemReportApi | null
}

export interface BriefingApi {
    id: string
    status: BriefingStatusApi
    items: BriefingItemApi[]
}

export interface RecordingTargetApi {
    session_id: string
    /** The finding's time in the recording, as MM:SS. */
    offset: string | null
    seek_seconds: number | null
}

/** Quiet lines are stack frames. */
export interface PreviewLineApi {
    text: string
    quiet: boolean
}

export interface SignalPreviewApi {
    block: PreviewLineApi[]
    facts: string[]
}

export interface SignalViewApi {
    signal_id: string
    source_product: string
    source_type: string
    content: string
    timestamp: string
    extra: Record<string, unknown>
    headline: string
    lead: string
    meta: string
    recording: RecordingTargetApi | null
    preview: SignalPreviewApi | null
}

export interface ImpactNumberApi {
    key: string
    value: string
    sentence: string
}

export interface ReportPageApi {
    /** The summary's opening paragraph, as markdown. */
    lead: string
    /** The impact section cut to whole sentences, as markdown. Empty when it states no measurement. */
    impact_sentence: string
    /** At most 3 signals, newest first, one per source first. */
    evidence: SignalViewApi[]
    impact_numbers: ImpactNumberApi[]
    last_seen: string | null
}

/** Starts today's briefing when there is none and returns it as `collecting`. */
export function fetchBriefing(timezone: string | null, signal?: AbortSignal): Promise<BriefingApi> {
    return apiJson<BriefingApi>(projectPath('today/briefing/'), { query: { timezone }, signal })
}

export function fetchReportPage(reportId: string, signal?: AbortSignal): Promise<ReportPageApi> {
    return apiJson<ReportPageApi>(projectPath(`today/reports/${encodeURIComponent(reportId)}/page/`), { signal })
}
