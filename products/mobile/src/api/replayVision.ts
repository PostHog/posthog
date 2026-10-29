import { ApiError, apiFetch, apiJson, projectPath } from './client'
import { type ProjectScope, scopeKey } from './reports'

// Shapes follow `ReplayObservationSerializer`, `InlineScanResponseSerializer` and `WatchFeedResponseSerializer` in
// `products/replay_vision/backend/api/`, keeping the fields the app reads. The summarizer's `model_output` follows
// `SummarizerOutput` in `products/replay_vision/backend/temporal/scanners/summarizer.py`.

export type ObservationStatusApi = 'pending' | 'running' | 'succeeded' | 'failed' | 'ineligible'

/** One persisted chapter, on the session clock. `idle` entries come from older scans and are skipped. */
export interface SummaryChapterApi {
    kind?: 'activity' | 'idle'
    start_ms: number
    end_ms?: number
    title: string
    thumbnail_ms?: number | null
}

/** `model_output`. Every scanner type carries `notability` and `key_moment_ms`; a summarizer adds the rest. */
export interface ModelOutputApi {
    scanner_type?: string
    title?: string
    summary?: string
    chapters?: SummaryChapterApi[]
    notability?: number | null
    notability_reason?: string | null
    key_moment_ms?: number | null
}

export interface ObservationMediaApi {
    kind: 'thumbnail' | 'chapter'
    position: number
}

export interface ObservationApi {
    id: string
    scanner_id: string
    session_id: string
    status: ObservationStatusApi
    scanner_snapshot?: { name?: string; scanner_type?: string } | null
    scanner_result?: { model_output?: ModelOutputApi | null } | null
    distinct_id?: string | null
    recording_subject_email?: string | null
    media?: ObservationMediaApi[]
    summary_line?: string
    /** On `failed` and `ineligible`: `kind:human-readable message`. */
    error_reason?: string
    completed_at?: string | null
    created_at?: string
}

export interface ObservationListApi {
    results?: ObservationApi[]
}

export async function fetchSessionObservations(sessionId: string, signal?: AbortSignal): Promise<ObservationListApi> {
    return apiJson<ObservationListApi>(projectPath('vision/observations/'), {
        query: { session_id: sessionId },
        signal,
    })
}

export type ScanOutcomeApi =
    | 'started'
    | 'already_running'
    | 'already_scanned'
    | 'skipped_limit'
    | 'skipped_quota'
    | 'skipped_scanner_limit'
    | 'failed'

export interface InlineScanResponseApi {
    scan_id: string | null
    started: number
    results?: { session_id: string; scan_outcome: ScanOutcomeApi }[]
}

/**
 * `POST vision/scanners/inline_scan/` with the built-in `summarize_recording`, the scan the web's Summarize button
 * runs, so both share one result. Needs `replay_scanner:write`. Answers 202 whatever the outcome, and 400 when the
 * organization has not approved AI data processing.
 */
export async function requestSessionSummary(sessionId: string, signal?: AbortSignal): Promise<ScanOutcomeApi | null> {
    const response = await apiJson<InlineScanResponseApi>(projectPath('vision/scanners/inline_scan/'), {
        method: 'POST',
        json: { built_in: 'summarize_recording', session_ids: [sessionId] },
        signal,
    })
    return response.results?.find((result) => result.session_id === sessionId)?.scan_outcome ?? null
}

export interface WatchFeedItemApi {
    observation: ObservationApi
    reason: { kind: string; notability?: number | null; notability_reason?: string | null }
}

export interface WatchFeedResponseApi {
    results?: WatchFeedItemApi[]
}

export const WATCH_FEED_LIMIT = 5

export async function fetchWatchFeed(signal?: AbortSignal): Promise<WatchFeedResponseApi> {
    return apiJson<WatchFeedResponseApi>(projectPath('vision/scanners/watch_feed/'), {
        query: { limit: WATCH_FEED_LIMIT, date_from: '-7d' },
        signal,
    })
}

/**
 * The address of one frame of an observation: its thumbnail, or one chapter's frame. The endpoint answers with a
 * redirect to a signed object-storage URL. The request does not follow it, so the bearer token never goes to the
 * storage host, and the image then loads from the signed URL without credentials. The global fetch on native is
 * `expo/fetch`, which hands back the 302 itself for `redirect: 'manual'`.
 */
export async function fetchFrameUrl(
    observationId: string,
    chapter: number | null,
    signal?: AbortSignal
): Promise<string> {
    const response = await apiFetch(
        projectPath(`vision/observations/${encodeURIComponent(observationId)}/thumbnail/`),
        {
            query: { chapter },
            redirect: 'manual',
            signal,
        }
    )
    const location = response.headers.get('Location')
    if (response.status >= 300 && response.status < 400 && location) {
        return location
    }
    if (response.ok) {
        // Local dev and a deployment without object storage serve the bytes from the API itself.
        return frameDataUri(await response.arrayBuffer(), response.headers.get('Content-Type') ?? 'image/png')
    }
    throw new ApiError(response.status, undefined, response.headers)
}

function frameDataUri(bytes: ArrayBuffer, contentType: string): string {
    const view = new Uint8Array(bytes)
    let binary = ''
    for (let index = 0; index < view.length; index += 0x8000) {
        binary += String.fromCharCode(...view.subarray(index, index + 0x8000))
    }
    return `data:${contentType};base64,${btoa(binary)}`
}

export const visionKeys = {
    all: (scope: ProjectScope | null) => ['vision', ...scopeKey(scope)] as const,
    session: (scope: ProjectScope | null, sessionId: string) =>
        [...visionKeys.all(scope), 'session', sessionId] as const,
    feed: (scope: ProjectScope | null) => [...visionKeys.all(scope), 'feed'] as const,
    frame: (scope: ProjectScope | null, observationId: string, chapter: number | null) =>
        [...visionKeys.all(scope), 'frame', observationId, chapter ?? 'thumbnail'] as const,
}
