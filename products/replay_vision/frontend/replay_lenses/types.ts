import { RecordingsQuery } from '~/queries/schema/schema-general'

import type { PatchedReplayLensApi, ReplayLensApi, ReplayObservationApi } from '../generated/api.schemas'

export type LensType = 'monitor' | 'classifier' | 'scorer' | 'summarizer' | 'indexer'

export type EnabledFilter = 'enabled' | 'disabled'

export type ObservationStatus = 'pending' | 'running' | 'succeeded' | 'failed'

export const DEFAULT_PROVIDER = 'google'
export const DEFAULT_MODEL = 'gemini-3-flash'

export const ENABLED_OPTIONS: { value: EnabledFilter; label: string }[] = [
    { value: 'enabled', label: 'Enabled' },
    { value: 'disabled', label: 'Disabled' },
]

export const MODEL_OPTIONS: { value: string; label: string }[] = [
    { value: 'gemini-3-flash', label: 'Gemini 3 Flash' },
    { value: 'gemini-3-flash-lite', label: 'Gemini 3 Flash Lite' },
]

export const LENS_TYPE_OPTIONS: { value: LensType; label: string; description: string }[] = [
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

export interface MonitorLensConfig {
    prompt: string
}

export interface SummarizerLensConfig {
    prompt: string
    length: 'short' | 'medium' | 'long'
}

export interface ClassifierLensConfig {
    prompt: string
    tags: string[]
    multi_label: boolean
}

export interface ScorerLensConfig {
    prompt: string
    scale: { min: number; max: number; label?: string }
}

export interface IndexerLensConfig {
    prompt: string
}

export type LensConfig =
    | MonitorLensConfig
    | SummarizerLensConfig
    | ClassifierLensConfig
    | ScorerLensConfig
    | IndexerLensConfig

export interface BaseReplayLens {
    id: string
    name: string
    description?: string
    enabled: boolean
    sampling_rate: number
    query: RecordingsQuery | null
    provider: string
    model: string
    emits_signals: boolean
    lens_version: number
    last_swept_at: string
    created_at: string
    updated_at: string
    created_by: { id: number; first_name: string; last_name?: string; email?: string } | null
    deleted?: boolean
}

export interface MonitorLens extends BaseReplayLens {
    lens_type: 'monitor'
    lens_config: MonitorLensConfig
}

export interface SummarizerLens extends BaseReplayLens {
    lens_type: 'summarizer'
    lens_config: SummarizerLensConfig
}

export interface ClassifierLens extends BaseReplayLens {
    lens_type: 'classifier'
    lens_config: ClassifierLensConfig
}

export interface ScorerLens extends BaseReplayLens {
    lens_type: 'scorer'
    lens_config: ScorerLensConfig
}

export interface IndexerLens extends BaseReplayLens {
    lens_type: 'indexer'
    lens_config: IndexerLensConfig
}

export type ReplayLens = MonitorLens | SummarizerLens | ClassifierLens | ScorerLens | IndexerLens

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

// The API exposes lens_config and query as `unknown`. The client narrows them via
// the lens_type discriminator, so conversion is contained to this single boundary.
export function lensFromApi(api: ReplayLensApi): ReplayLens {
    return api as unknown as ReplayLens
}

export function lensesFromApi(apis: readonly ReplayLensApi[]): ReplayLens[] {
    return apis.map(lensFromApi)
}

export function lensToApiBody(lens: Partial<ReplayLens> | Record<string, unknown>): ReplayLensApi {
    return lens as unknown as ReplayLensApi
}

export function lensToPatchedApiBody(lens: Partial<ReplayLens> | Record<string, unknown>): PatchedReplayLensApi {
    return lens as unknown as PatchedReplayLensApi
}

export function observationsFromApi(apis: readonly ReplayObservationApi[]): ReplayObservation[] {
    return apis.map((api) => api as unknown as ReplayObservation)
}

export interface ReplayObservation {
    id: string
    lens_id: string
    session_id: string
    status: ObservationStatus
    error_reason: string
    workflow_id: string
    lens_version: number
    lens_config_snapshot: Record<string, unknown>
    model_used: string
    provider_used: string
    triggered_by: 'schedule' | 'on_demand'
    triggered_by_user: { id: number; first_name: string } | null
    result: Record<string, unknown> | null
    created_at: string
    started_at: string | null
    completed_at: string | null
}
