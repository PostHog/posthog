import { RecordingsQuery } from '~/queries/schema/schema-general'

import type { PatchedReplayScannerApi, ReplayScannerApi } from '../generated/api.schemas'

export type ScannerType = 'monitor' | 'classifier' | 'scorer' | 'summarizer' | 'indexer'

export type EnabledFilter = 'enabled' | 'disabled'

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
