import { LemonTagType } from '@posthog/lemon-ui'

import { RecordingsQuery } from '~/queries/schema/schema-general'

import { ScannerModelEnumApi } from '../generated/api.schemas'
import type {
    PatchedReplayScannerApi,
    ReplayScannerApi,
    ScannerTypeEnumApi,
    UserBasicApi,
} from '../generated/api.schemas'

export type ScannerType = ScannerTypeEnumApi

export const SCANNER_TYPE_TAG_TYPE: Record<ScannerType, LemonTagType> = {
    monitor: 'primary',
    classifier: 'completion',
    scorer: 'warning',
    summarizer: 'success',
}

export type EnabledFilter = 'enabled' | 'disabled'

export type IneligibleKind = 'no_recording' | 'too_short' | 'too_inactive' | 'too_long' | 'no_events'

const INELIGIBLE_KINDS: Record<IneligibleKind, { label: string; description: string }> = {
    no_recording: { label: 'No recording', description: 'No recording was found for this session.' },
    too_short: { label: 'Too short', description: 'The session was too short to analyze.' },
    too_inactive: { label: 'Too inactive', description: 'The session had too little active interaction to analyze.' },
    too_long: { label: 'Too long', description: 'The session was too long to analyze.' },
    no_events: { label: 'No events', description: 'The session had no events to analyze.' },
}

export type FailureKind =
    | 'provider_transient'
    | 'provider_rejected'
    | 'rasterization_failed'
    | 'validation_failed'
    | 'internal_error'
    | 'orphaned'

const FAILURE_KINDS: Record<FailureKind, { label: string; description: string }> = {
    provider_transient: {
        label: 'AI provider unavailable',
        description:
            "The AI provider was temporarily unreachable. PostHog will retry on the scanner's next scheduled run.",
    },
    provider_rejected: {
        label: 'AI provider rejected video',
        description: "The AI provider couldn't process this recording. Try a different one.",
    },
    rasterization_failed: {
        label: 'Recording video failed',
        description:
            "PostHog couldn't render this recording into a video for the AI. Try again, or run the scanner on a different recording.",
    },
    validation_failed: {
        label: 'AI output invalid',
        description:
            'The AI returned malformed output after several attempts. Try simplifying or rephrasing the scanner prompt.',
    },
    internal_error: {
        label: 'Internal error',
        description: 'An unexpected PostHog error occurred. Please contact support.',
    },
    orphaned: {
        label: 'Interrupted',
        description:
            'The analysis was interrupted before finishing and has been cleaned up. Run the scanner on this recording again if needed.',
    },
}

export type ParsedReason<K extends string> = { kind: K; label: string; message: string }

function parseKindReason<K extends string>(
    error_reason: string,
    kinds: Record<K, { label: string }>
): ParsedReason<K> | null {
    // The backend formats `error_reason` as `kind:human message`; fall back to a generic label on drift.
    const idx = error_reason.indexOf(':')
    if (idx <= 0) {
        return null
    }
    const kind = error_reason.slice(0, idx)
    if (!(kind in kinds)) {
        return null
    }
    return {
        kind: kind as K,
        label: kinds[kind as K].label,
        message: error_reason.slice(idx + 1).trim(),
    }
}

export function parseIneligibleReason(error_reason: string): ParsedReason<IneligibleKind> | null {
    return parseKindReason(error_reason, INELIGIBLE_KINDS)
}

export function parseFailureReason(error_reason: string): ParsedReason<FailureKind> | null {
    return parseKindReason(error_reason, FAILURE_KINDS)
}

export function failureKindDescription(kind: FailureKind): string {
    return FAILURE_KINDS[kind].description
}

export function ineligibleKindDescription(kind: IneligibleKind): string {
    return INELIGIBLE_KINDS[kind].description
}

export const DEFAULT_PROVIDER = 'google'
export const DEFAULT_MODEL: ScannerModelEnumApi = ScannerModelEnumApi.Gemini3FlashPreview

export const ENABLED_OPTIONS: { value: EnabledFilter; label: string }[] = [
    { value: 'enabled', label: 'Enabled' },
    { value: 'disabled', label: 'Disabled' },
]

export const MODEL_OPTIONS: { value: ScannerModelEnumApi; label: string }[] = [
    { value: ScannerModelEnumApi.Gemini3FlashPreview, label: 'Gemini 3 Flash' },
    { value: ScannerModelEnumApi.Gemini31FlashLitePreview, label: 'Gemini 3 Flash Lite' },
]

export function modelLabel(model: string | null | undefined): string {
    if (!model) {
        return '—'
    }
    return MODEL_OPTIONS.find((opt) => opt.value === model)?.label ?? model
}

export function scannerTypeLabel(scannerType: ScannerType | null | undefined): string {
    if (!scannerType) {
        return '—'
    }
    return SCANNER_TYPE_OPTIONS.find((opt) => opt.value === scannerType)?.label ?? scannerType
}

export function createdByLabel(user: ScannerCreatedBy | null): string {
    if (!user) {
        return ''
    }
    const name = [user.first_name, user.last_name].filter(Boolean).join(' ').trim()
    return name || user.email || `User ${user.id}`
}

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
]

export interface MonitorScannerConfig {
    prompt: string
    allow_inconclusive?: boolean
}

export interface SummarizerScannerConfig {
    prompt: string
    length: 'short' | 'medium' | 'long'
}

export interface ClassifierScannerConfig {
    prompt: string
    tags: string[]
    multi_label: boolean
    allow_freeform_tags?: boolean
}

export interface ScorerScannerConfig {
    prompt: string
    scale: { min: number; max: number; label?: string }
}

export type ScannerConfig =
    | MonitorScannerConfig
    | SummarizerScannerConfig
    | ClassifierScannerConfig
    | ScorerScannerConfig

// hedgehog_config's nullable index-signature type trips DeepPartial and ProfilePicture; the UI never reads it.
export type ScannerCreatedBy = Omit<UserBasicApi, 'hedgehog_config'>

// Derived from the generated schema so serializer changes fail typecheck; write-optional fields carry defaults.
export type BaseReplayScanner = Omit<ReplayScannerApi, 'scanner_type' | 'scanner_config' | 'query' | 'created_by'> &
    Required<Pick<ReplayScannerApi, 'sampling_rate' | 'enabled' | 'emits_signals' | 'provider'>> & {
        query: RecordingsQuery | null
        created_by: ScannerCreatedBy | null
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

export type ReplayScanner = MonitorScanner | SummarizerScanner | ClassifierScanner | ScorerScanner

/** Narrow a snapshot's untyped scanner_config at one boundary; pair with the snapshot's scanner_type to pick the variant. */
export function configFromSnapshot(snapshot: { scanner_config?: unknown } | null | undefined): ScannerConfig | null {
    const config = snapshot?.scanner_config
    return config && typeof config === 'object' ? (config as ScannerConfig) : null
}

// The API types scanner_config and query as `unknown`; the scanner_type discriminator narrows them here only.
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
