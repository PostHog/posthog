import { LemonTagType } from '@posthog/lemon-ui'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { AccessControlLevel } from '~/types'

import { ScannerModelEnumApi } from '../generated/api.schemas'
import type {
    PatchedReplayScannerApi,
    ReplayObservationApi,
    ReplayScannerApi,
    ScannerTypeEnumApi,
    UserBasicApi,
    VisionObservationsRetrieveParams,
} from '../generated/api.schemas'
import { formatCreditCount } from '../utils/credits'

export type ScannerType = ScannerTypeEnumApi

export const SCANNER_TYPE_TAG_TYPE: Record<ScannerType, LemonTagType> = {
    monitor: 'primary',
    classifier: 'completion',
    scorer: 'warning',
    summarizer: 'success',
}

export const OBSERVATION_TRIGGER_TAG: Record<
    ReplayObservationApi['triggered_by'],
    { label: string; type: LemonTagType }
> = {
    schedule: { label: 'Schedule', type: 'default' },
    on_demand: { label: 'On demand', type: 'highlight' },
    retry: { label: 'Retry', type: 'completion' },
    backfill: { label: 'Backfill', type: 'caution' },
}

// Typed against the generated retrieve params so a renamed or dropped backend filter fails the build.
export const OBSERVATION_LIST_FILTER_KEYS: readonly (keyof VisionObservationsRetrieveParams)[] = [
    'status',
    'triggered_by',
    'verdict',
    'tags',
    'min_score',
    'max_score',
    'session_id',
    'recording_subject',
    'labeled',
    'order_by',
]

export type EnabledFilter = 'enabled' | 'disabled'

export type IneligibleKind =
    | 'no_recording'
    | 'no_snapshots'
    | 'too_short'
    | 'too_inactive'
    | 'too_long'
    | 'no_events'
    | 'no_ai_consent'

type IneligibleKindInfo = {
    label: string
    description: string
    /** Set where the gate can be a timing artifact rather than a property of the session, so a retry is offered. */
    retryable?: boolean
    /** Why a retry might change the outcome. Shown on the retry control. */
    retryHint?: string
}

const INELIGIBLE_KINDS: Record<IneligibleKind, IneligibleKindInfo> = {
    no_recording: { label: 'No recording', description: 'No recording was found for this session.' },
    no_snapshots: {
        label: 'Nothing to play back',
        description:
            'This recording has no screen data to play back, so there was no video for the AI to watch. If you expect this recording to have visuals, its screen data may still be ingesting. Retry the scan later.',
        retryable: true,
        retryHint: 'Screen data can finish ingesting after a scan. Retry if you expect this recording to play back.',
    },
    too_short: { label: 'Too short', description: 'The session was too short to analyze.' },
    too_inactive: { label: 'Too inactive', description: 'The session had too little active interaction to analyze.' },
    too_long: { label: 'Too long', description: 'The session was too long to analyze.' },
    no_events: { label: 'No events', description: 'The session had no events to analyze.' },
    no_ai_consent: {
        label: 'AI analysis not allowed',
        description:
            'AI data processing is turned off for this organization, so this recording was not analyzed. An organization admin can turn it on in organization settings.',
        retryable: true,
        retryHint: 'If AI data processing has been turned on since, retry the scan.',
    },
}

export type FailureKind =
    | 'provider_transient'
    | 'provider_rejected'
    | 'rasterization_failed'
    | 'validation_failed'
    | 'infra_transient'
    | 'internal_error'
    | 'orphaned'

type FailureKindInfo = {
    label: string
    description: string
    /** Whether one more attempt at the same recording can plausibly land differently. Drives how retry is offered. */
    retryWorthwhile: boolean
    /** Why a plain retry probably isn't the next step. Shown on the retry control when set. */
    retryHint?: string
}

const FAILURE_KINDS: Record<FailureKind, FailureKindInfo> = {
    provider_transient: {
        label: 'AI provider unavailable',
        description: 'The AI provider stayed unreachable across every automatic retry. Retry the scan.',
        retryWorthwhile: true,
    },
    provider_rejected: {
        label: 'AI provider rejected the video',
        description:
            "The AI provider wouldn't analyze this recording's video. Retrying reaches the same answer, so run the scanner on a different recording.",
        retryWorthwhile: false,
        retryHint: 'The provider already declined this video, so a retry will most likely fail the same way.',
    },
    rasterization_failed: {
        label: 'Recording video failed',
        description:
            'PostHog could not turn this recording into a video for the AI. Retry the scan, and contact support if it fails again.',
        retryWorthwhile: true,
    },
    validation_failed: {
        label: 'AI output did not fit the scanner',
        description:
            "The AI could not answer in this scanner's format, across two separate attempts. Simplify or rephrase the scanner prompt, then retry.",
        retryWorthwhile: false,
        retryHint: "A retry runs the scanner's current prompt. Edit the prompt first if you haven't changed it yet.",
    },
    infra_transient: {
        label: 'PostHog timed out',
        description: 'A PostHog service took too long while preparing this recording. Retry the scan in a few minutes.',
        retryWorthwhile: true,
    },
    internal_error: {
        label: 'Internal error',
        description: 'Something inside PostHog stopped this scan. Retry it, and contact support if it fails again.',
        retryWorthwhile: true,
    },
    orphaned: {
        label: 'Interrupted',
        description: 'The scan was interrupted before it finished, and PostHog cleaned it up. Retry the scan.',
        retryWorthwhile: true,
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

/**
 * How to offer a retry for a given failure. An unparseable or unknown kind gets the encouraging default, since
 * the alternative is discouraging a retry we have no evidence against.
 */
export function failureRetryGuidance(kind: FailureKind | null): { worthwhile: boolean; hint: string | null } {
    const info = kind ? FAILURE_KINDS[kind] : null
    return { worthwhile: info?.retryWorthwhile ?? true, hint: info?.retryHint ?? null }
}

export type ObservationRetryOffer = { show: boolean; worthwhile: boolean; hint: string | null }

/**
 * Whether and how to offer a retry for an observation. Failed observations always offer it, because the user can
 * know things we don't (that they just rewrote the scanner prompt, say). The retry endpoint accepts any failed or
 * ineligible observation; the UI additionally narrows ineligible offers to kinds whose outcome can change (late
 * snapshots, consent turned on), so deterministic gates like too_short don't grow a pointless button.
 */
export function observationRetryOffer(
    status: ReplayObservationApi['status'],
    errorReason: string | null | undefined
): ObservationRetryOffer {
    if (status === 'failed') {
        const kind = errorReason ? (parseFailureReason(errorReason)?.kind ?? null) : null
        return { show: true, ...failureRetryGuidance(kind) }
    }
    if (status === 'ineligible' && errorReason) {
        const parsed = parseIneligibleReason(errorReason)
        const info = parsed ? INELIGIBLE_KINDS[parsed.kind] : null
        if (info?.retryable) {
            return { show: true, worthwhile: false, hint: info.retryHint ?? null }
        }
    }
    return { show: false, worthwhile: false, hint: null }
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

// Mirrors the backend `OBSERVATION_CREDITS_BY_MODEL` table (the scanner/estimate API responses are authoritative);
// the picker needs a price per model before anything is saved, so it can't come from a per-instance response.
export const OBSERVATION_CREDITS_BY_MODEL: Record<ScannerModelEnumApi, number> = {
    [ScannerModelEnumApi.Gemini35FlashLite]: 2,
    [ScannerModelEnumApi.Gemini3FlashPreview]: 5,
    [ScannerModelEnumApi.Gemini37Flash]: 15,
}

const MODEL_NAMES: Record<ScannerModelEnumApi, string> = {
    [ScannerModelEnumApi.Gemini35FlashLite]: 'Gemini 3.5 Flash Lite',
    [ScannerModelEnumApi.Gemini3FlashPreview]: 'Gemini 3 Flash',
    [ScannerModelEnumApi.Gemini37Flash]: 'Gemini 3.7 Flash',
}

// Tier-name arms of the replay-vision-model-tier-naming-experiment flag: capability tiers instead
// of provider model names, keyed by the flag's variant key. Every surface that shows a model must
// resolve the variant the same way so a user never sees mixed naming schemes for one scanner.
export type ModelNamingVariant = 'test' | 'lite-standard-pro'

const MODEL_TIER_NAMES: Record<ModelNamingVariant, Record<ScannerModelEnumApi, string>> = {
    test: {
        [ScannerModelEnumApi.Gemini35FlashLite]: 'Basic',
        [ScannerModelEnumApi.Gemini3FlashPreview]: 'Pro',
        [ScannerModelEnumApi.Gemini37Flash]: 'Ultra',
    },
    'lite-standard-pro': {
        [ScannerModelEnumApi.Gemini35FlashLite]: 'Lite',
        [ScannerModelEnumApi.Gemini3FlashPreview]: 'Standard',
        [ScannerModelEnumApi.Gemini37Flash]: 'Pro',
    },
}

// Narrows a raw flag value to a naming variant. Control, booleans, and variant keys this build
// doesn't know yet all resolve to null (provider model names), so a flag/frontend version skew
// degrades to the control experience instead of mislabeling an arm.
export function modelNamingVariant(flagValue: unknown): ModelNamingVariant | null {
    return typeof flagValue === 'string' && flagValue in MODEL_TIER_NAMES ? (flagValue as ModelNamingVariant) : null
}

export function getModelOptions(
    namingVariant: ModelNamingVariant | null
): { value: ScannerModelEnumApi; label: string }[] {
    return Object.values(ScannerModelEnumApi).map((value) => ({
        value,
        label: `${modelName(value, namingVariant)} · ${formatCreditCount(OBSERVATION_CREDITS_BY_MODEL[value])}/observation`,
    }))
}

// Falls back to the raw id for retired models frozen in old observation snapshots.
export function modelLabel(model: string | null | undefined, namingVariant: ModelNamingVariant | null = null): string {
    if (!model) {
        return '—'
    }
    return getModelOptions(namingVariant).find((opt) => opt.value === model)?.label ?? model
}

/** Plain model name without the price suffix, for surfaces that show the price separately. */
export function modelName(model: string | null | undefined, namingVariant: ModelNamingVariant | null = null): string {
    if (!model) {
        return '—'
    }
    const names = namingVariant ? MODEL_TIER_NAMES[namingVariant] : MODEL_NAMES
    return names[model as ScannerModelEnumApi] ?? model
}

/** Fallback name for a scanner the user never named, e.g. "Hedgebox classifier". */
export function defaultScannerName(teamName: string | null | undefined, scannerType: ScannerType): string {
    const type = scannerTypeLabel(scannerType).toLowerCase()
    return teamName ? `${teamName} ${type}` : `New ${type}`
}

export function scannerTypeLabel(scannerType: ScannerType | null | undefined): string {
    if (!scannerType) {
        return '—'
    }
    return SCANNER_TYPE_OPTIONS.find((opt) => opt.value === scannerType)?.label ?? scannerType
}

// A plain-language description of what each scanner type produces per session, for people who don't yet
// know the type names. Kept short so it reads as a chip subtitle / tooltip.
const SCANNER_TYPE_OUTPUT_HINT: Record<ScannerType, string> = {
    monitor: 'yes or no',
    classifier: 'a category from a set you define',
    scorer: 'a number score',
    summarizer: 'a text summary',
}

export function scannerTypeOutputHint(scannerType: ScannerType): string {
    return SCANNER_TYPE_OUTPUT_HINT[scannerType]
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
        description: 'Sorts the session into one or more categories you define.',
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

export type SamplingMode = 'focused' | 'balanced' | 'comprehensive'

// Ordered broadest to narrowest so the labels read as a ladder.
export const SAMPLING_MODE_OPTIONS: { value: SamplingMode; label: string; description: string }[] = [
    {
        value: 'comprehensive',
        label: 'All recordings',
        description: 'Scans everything that matches your filters, whatever happens in the recording.',
    },
    {
        value: 'balanced',
        label: 'Medium and high activity recordings',
        description: 'Skips recordings where almost nothing happens.',
    },
    {
        value: 'focused',
        label: 'High activity recordings only',
        description: 'Scans just the busiest recordings. The fewest, and the most likely to be interesting.',
    },
]

// hedgehog_config's nullable index-signature type trips DeepPartial and ProfilePicture; the UI never reads it.
export type ScannerCreatedBy = Omit<UserBasicApi, 'hedgehog_config'>

// Derived from the generated schema so serializer changes fail typecheck; write-optional fields carry defaults.
export type BaseReplayScanner = Omit<
    ReplayScannerApi,
    'scanner_type' | 'scanner_config' | 'query' | 'created_by' | 'user_access_level'
> &
    Required<
        Pick<ReplayScannerApi, 'sampling_rate' | 'enabled' | 'emits_signals' | 'provider' | 'credit_limit' | 'tags'>
    > & {
        query: RecordingsQuery | null
        created_by: ScannerCreatedBy | null
        sampling_mode: SamplingMode
        user_access_level: AccessControlLevel | null
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

// The editor form's values: the API scanner plus UI-only state that is stripped before every API write.
// `credit_limit_enabled` keeps "limit toggle on, amount still empty" representable so it can block the save.
export type ScannerFormValues = ReplayScanner & { credit_limit_enabled?: boolean }

// Mirrors the API's int4 bound on credit_limit (visionScannersCreateBodyCreditLimitMax in generated/api.zod.ts).
export const MAX_CREDIT_LIMIT = 2147483647

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
