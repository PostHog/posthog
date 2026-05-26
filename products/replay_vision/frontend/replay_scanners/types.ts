import { RecordingsQuery } from '~/queries/schema/schema-general'

import type { PatchedReplayScannerApi, ReplayScannerApi } from '../generated/api.schemas'

export type ScannerType = 'monitor' | 'classifier' | 'scorer' | 'summarizer' | 'indexer'

export type EnabledFilter = 'enabled' | 'disabled'

export type IneligibleKind = 'no_recording' | 'too_short' | 'too_inactive' | 'too_long' | 'no_events'

const INELIGIBLE_KIND_LABELS: Record<IneligibleKind, string> = {
    no_recording: 'No recording',
    too_short: 'Too short',
    too_inactive: 'Too inactive',
    too_long: 'Too long',
    no_events: 'No events',
}

export type FailureKind =
    | 'provider_transient'
    | 'provider_rejected'
    | 'rasterization_failed'
    | 'validation_failed'
    | 'internal_error'

const FAILURE_KINDS: Record<FailureKind, { label: string; description: string }> = {
    provider_transient: {
        label: 'AI provider unavailable',
        description: 'The AI provider was temporarily unreachable. PostHog will retry on the next schedule fire.',
    },
    provider_rejected: {
        label: 'AI provider rejected video',
        description: "The AI provider couldn't process this recording. Other recordings should work.",
    },
    rasterization_failed: {
        label: 'Rasterization failed',
        description: "PostHog couldn't render this recording into a video. Other recordings should work.",
    },
    validation_failed: {
        label: 'AI output invalid',
        description:
            "The AI's response didn't match the scanner schema after several attempts. Try simplifying the scanner prompt.",
    },
    internal_error: {
        label: 'Internal error',
        description: 'An unexpected PostHog error occurred. Please contact support.',
    },
}

const FAILURE_KIND_LABELS = Object.fromEntries(
    Object.entries(FAILURE_KINDS).map(([kind, meta]) => [kind, meta.label])
) as Record<FailureKind, string>

export type ParsedReason<K extends string> = { kind: K; label: string; message: string }

function parseKindReason<K extends string>(error_reason: string, labels: Record<K, string>): ParsedReason<K> | null {
    // The backend formats `error_reason` as `kind:human message`; fall back to a generic label on drift.
    const idx = error_reason.indexOf(':')
    if (idx <= 0) {
        return null
    }
    const kind = error_reason.slice(0, idx)
    if (!(kind in labels)) {
        return null
    }
    return {
        kind: kind as K,
        label: labels[kind as K],
        message: error_reason.slice(idx + 1).trim(),
    }
}

export function parseIneligibleReason(error_reason: string): ParsedReason<IneligibleKind> | null {
    return parseKindReason(error_reason, INELIGIBLE_KIND_LABELS)
}

export function parseFailureReason(error_reason: string): ParsedReason<FailureKind> | null {
    return parseKindReason(error_reason, FAILURE_KIND_LABELS)
}

export function failureKindDescription(kind: FailureKind): string {
    return FAILURE_KINDS[kind].description
}

export const DEFAULT_PROVIDER = 'google'
export const DEFAULT_MODEL = 'gemini-3-flash-preview'

export const ENABLED_OPTIONS: { value: EnabledFilter; label: string }[] = [
    { value: 'enabled', label: 'Enabled' },
    { value: 'disabled', label: 'Disabled' },
]

export const MODEL_OPTIONS: { value: string; label: string }[] = [
    { value: 'gemini-3-flash-preview', label: 'Gemini 3 Flash' },
    { value: 'gemini-3.1-flash-lite-preview', label: 'Gemini 3 Flash Lite' },
]

export const SCANNER_TYPE_OPTIONS: { value: ScannerType; label: string; description: string }[] = [
    {
        value: 'monitor',
        label: 'Monitor',
        description: 'Detects whether a specific condition occurred in the session.',
    },
    {
        value: 'summarizer',
        label: 'Summarizer',
        description: 'Produces a title and a text summary of what happened in the session.',
    },
    {
        value: 'classifier',
        label: 'Classifier',
        description: 'Tags the session with one or more categories from a fixed vocabulary.',
    },
    {
        value: 'scorer',
        label: 'Scorer',
        description: 'Scores the session on a configurable numeric scale.',
    },
    {
        value: 'indexer',
        label: 'Indexer',
        description: 'Generates semantic embeddings of the session for free-text search.',
    },
]

export type EditorTab = 'configuration' | 'triggers' | 'observations'

export const ALL_EDITOR_TABS: EditorTab[] = ['configuration', 'triggers', 'observations']

export interface MonitorScannerConfig {
    prompt: string
}

export interface SummarizerScannerConfig {
    prompt: string
    length: 'short' | 'medium' | 'long'
}

export interface ClassifierScannerConfig {
    prompt: string
    tags: string[]
    multi_label: boolean
}

export interface ScorerScannerConfig {
    prompt: string
    scale: { min: number; max: number; label?: string }
}

export interface IndexerScannerConfig {
    prompt: string
}

export type ScannerConfig =
    | MonitorScannerConfig
    | SummarizerScannerConfig
    | ClassifierScannerConfig
    | ScorerScannerConfig
    | IndexerScannerConfig

export interface BaseReplayScanner {
    id: string
    name: string
    description?: string
    enabled: boolean
    sampling_rate: number
    query: RecordingsQuery | null
    provider: string
    model: string
    emits_signals: boolean
    scanner_version: number
    last_swept_at: string
    created_at: string
    updated_at: string
    created_by: { id: number; first_name: string; last_name?: string; email?: string } | null
    deleted?: boolean
}

export interface MonitorScanner extends BaseReplayScanner {
    scanner_type: 'monitor'
    scanner_config: MonitorScannerConfig
}

export interface SummarizerScanner extends BaseReplayScanner {
    scanner_type: 'summarizer'
    scanner_config: SummarizerScannerConfig
}

export interface ClassifierScanner extends BaseReplayScanner {
    scanner_type: 'classifier'
    scanner_config: ClassifierScannerConfig
}

export interface ScorerScanner extends BaseReplayScanner {
    scanner_type: 'scorer'
    scanner_config: ScorerScannerConfig
}

export interface IndexerScanner extends BaseReplayScanner {
    scanner_type: 'indexer'
    scanner_config: IndexerScannerConfig
}

export type ReplayScanner = MonitorScanner | SummarizerScanner | ClassifierScanner | ScorerScanner | IndexerScanner

export interface VisionUsagePoint {
    date: string
    count: number
}

export interface VisionQuota {
    used: number
    limit: number
    policy: 'block' | 'usage_based'
    period_start: string
    period_end: string
    /** Daily observation counts across the current period. Optional until the backend exposes it. */
    usage_history?: VisionUsagePoint[]
}

// The API exposes scanner_config and query as `unknown`. The client narrows them via
// the scanner_type discriminator, so conversion is contained to this single boundary.
export function scannerFromApi(api: ReplayScannerApi): ReplayScanner {
    return api as unknown as ReplayScanner
}

export function scannersFromApi(apis: readonly ReplayScannerApi[]): ReplayScanner[] {
    return apis.map(scannerFromApi)
}

export function scannerToApiBody(scanner: Partial<ReplayScanner> | Record<string, unknown>): ReplayScannerApi {
    return scanner as unknown as ReplayScannerApi
}

export function scannerToPatchedApiBody(
    scanner: Partial<ReplayScanner> | Record<string, unknown>
): PatchedReplayScannerApi {
    return scanner as unknown as PatchedReplayScannerApi
}
