import { apiJson, projectPath } from './client'

// Shapes follow `products/today/backend/presentation/serializers.py`. The page returns 404 when the project or person
// has no Today (flag off, no AI data processing approval, no AI credits); the report screen then shows signals instead.

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

export function fetchReportPage(reportId: string, signal?: AbortSignal): Promise<ReportPageApi> {
    return apiJson<ReportPageApi>(projectPath(`today/reports/${encodeURIComponent(reportId)}/page/`), { signal })
}
