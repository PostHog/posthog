import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    isBreakpoint,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { forms } from 'kea-forms'
import type { DeepPartial, DeepPartialMap, FieldName, ValidationErrorType } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, beforeUnload, router, urlToAction } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { scrollToFormError } from 'lib/forms/scrollToFormError'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { organizationLogic } from 'scenes/organizationLogic'
import { recordingsQueryToUniversalFilters } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { NodeKind, type RecordingsQuery } from '~/queries/schema/schema-general'

import type { ExperimentBasicApi } from 'products/experiments/frontend/generated/api.schemas'

import {
    visionScannersAffectedCohortCreate,
    visionScannersCreate,
    visionScannersDraftCreate,
    visionScannersEstimateCreate,
    visionScannersObservationsList,
    visionScannersObservationsStatsRetrieve,
    visionScannersObserveCreate,
    visionScannersPartialUpdate,
    visionScannersRetrieve,
} from '../generated/api'
import { ObservationStatusEnumApi, ObservationTriggerEnumApi } from '../generated/api.schemas'
import type {
    DraftScannerResponseApi,
    EstimateResponseApi,
    ObservationStatsApi,
    ReplayObservationApi,
    ReplayScannerApi,
} from '../generated/api.schemas'
import type { ScannerCreationMethodEnumApi, ScannerTypeEnumApi } from '../generated/api.schemas'
import { OBSERVE_POLL_GRACE_MS, scheduleObservationPoll, shouldPollObservations } from '../logics/observationPolling'
import { requestObservationRetry } from '../logics/observationRetry'
import { refreshVisionQuota, visionQuotaLogic } from '../logics/visionQuotaLogic'
import { neighborFilterParams } from '../observations/replayObservationLogic'
import { lastObservationsPage } from '../observations/replayObservationSceneLogic'
import { observationClipboardText } from '../utils/observation'
import {
    type UrlSorting,
    parseCsvParam,
    parseNumericParam,
    parseSortParam,
    serializeSortParam,
} from '../utils/urlParams'
import { clampDurationFilter, durationFilterError } from './durationBounds'
import {
    ExperimentScannerContext,
    buildExperimentTargeting,
    experimentScannerConfig,
    experimentScannerName,
    experimentScannerQuery,
    parseExperimentScannerParams,
    prefillScannerForExperiment,
    ScannerExperimentScope,
    reconcileVariantKey,
    scannerExperimentScope,
} from './experimentTargeting'
import { newScanner } from './newScanner'
import { ReplayScannerTab } from './replayScannerSceneLogic'
import { clearScannerDraft, readScannerDraft, writeScannerDraft } from './scannerDraft'
import {
    ScannerEditorStep,
    advancesWithoutSubmit,
    firstErroredScannerStep,
    nextScannerEditorStep,
    scannerEditorSceneLogic,
    scannerEditorSteps,
    scannerStepErrors,
    scannerStepUrl,
    scannerStepUrlWithParams,
} from './scannerEditorSceneLogic'
import { consumeScannerGoalDraftIntent, consumeScannerHandoffIntent } from './scannerHandoffIntent'
import type { ObservationStatusStats } from './scannerStats'
import { availableTagsFromStats, daysFromDateRange, deriveObservationStatusStats } from './scannerStats'
import {
    ExperimentScannerConfig,
    MAX_CREDIT_LIMIT,
    OBSERVATION_CREDITS_BY_MODEL,
    OBSERVATION_LIST_URL_PARAM_KEYS,
    SamplingMode,
    ScannerConfig,
    defaultScannerName,
    ScannerFormValues,
    ScannerType,
    ReplayScanner,
    scannerFromApi,
    scannerToApiBody,
    scannerToPatchedApiBody,
} from './types'

/** Narrows a cohort to one monitor verdict or one classifier category; empty means the type's default. */
export interface AffectedCohortQualifier {
    verdict?: ObservationVerdictValue
    tag?: string
}

export interface ReplayScannerLogicProps {
    id: string
}

export type ObservationStatusValue = ReplayObservationApi['status']
export type ObservationTriggeredByValue = ReplayObservationApi['triggered_by']
export type ObservationVerdictValue = 'yes' | 'no' | 'inconclusive'

// Derived from the generated runtime enums so a backend enum change can't strand a stale copy here.
const OBSERVATION_STATUS_VALUES: readonly ObservationStatusValue[] = Object.values(ObservationStatusEnumApi)
const OBSERVATION_TRIGGERED_BY_VALUES: readonly ObservationTriggeredByValue[] = Object.values(ObservationTriggerEnumApi)
const OBSERVATION_VERDICT_VALUES: readonly ObservationVerdictValue[] = ['yes', 'no', 'inconclusive']

export const OBSERVATIONS_PAGE_SIZE = 50
/** Newest first: the sort the table falls back to, and the one the URL leaves out. */
const DEFAULT_OBSERVATIONS_SORT: ObservationsSorting = { columnKey: 'created_at', order: -1 }
// Past this many rows the clipboard is the wrong tool.
const COPY_ALL_OBSERVATIONS_LIMIT = 500

// The filter UI spreads each of these straight into its list of filter values, so a string here
// renders one filter per character instead of failing.
const PREFILL_QUERY_LIST_FIELDS = [
    'events',
    'actions',
    'properties',
    'console_log_filters',
    'having_predicates',
] as const

function isValidPrefillQuery(parsed: unknown): parsed is RecordingsQuery {
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return false
    }
    const query = parsed as Record<string, unknown>
    if ('kind' in query && query.kind !== NodeKind.RecordingsQuery) {
        return false
    }
    return PREFILL_QUERY_LIST_FIELDS.every((field) => !(field in query) || Array.isArray(query[field]))
}

/**
 * A `RecordingsQuery` handed to the new-scanner wizard via `?filters=<url-encoded JSON>`, used by
 * cross-sell entry points (e.g. "save these filters as a scanner" in the replay playlist) to seed
 * the scanner's query. Returns null on a missing, unparseable, or wrong-shaped param so a malformed
 * link just opens the blank wizard rather than throwing or rendering nonsense filters.
 */
function prefillQueryFromUrl(): RecordingsQuery | null {
    const value = router.values.searchParams.filters
    if (typeof value !== 'string' || !value) {
        return null
    }
    try {
        const parsed = JSON.parse(value)
        return isValidPrefillQuery(parsed) ? parsed : null
    } catch {
        return null
    }
}

function defaultConfigForType(scannerType: ScannerType): ScannerConfig {
    if (scannerType === 'summarizer') {
        return { prompt: '', length: 'medium' }
    }
    if (scannerType === 'classifier') {
        return { prompt: '', tags: [], multi_label: true }
    }
    if (scannerType === 'scorer') {
        return { prompt: '', scale: { min: 0, max: 10 } }
    }
    if (scannerType === 'experiment') {
        return { prompt: '', length: 'medium', experiment_id: null, variants: null, balance_variants: true }
    }
    return { prompt: '' }
}

/** Until experiment scanners ship, the experiment entry points keep creating legacy targeting. */
function experimentScannersEnabled(): boolean {
    return !!featureFlagLogic.values.featureFlags[FEATURE_FLAGS.VISION_EXPERIMENT_SCANNER]
}

function draftExperimentScope(goalDraft: DraftScannerResponseApi): ScannerExperimentScope | null {
    if (goalDraft.scanner_type !== 'experiment') {
        return null
    }
    const config = goalDraft.scanner_config as ExperimentScannerConfig
    return config.experiment_id ? { experimentId: config.experiment_id, variants: config.variants ?? null } : null
}

/** A draft that watches an experiment becomes the experiment type, keeping the drafted prompt as its focus. */
function draftScannerTypeAndConfig(
    goalDraft: DraftScannerResponseApi,
    draftedExperiment: ScannerExperimentScope | null,
    context: ExperimentScannerContext | null
): Pick<ScannerFormValues, 'scanner_type' | 'scanner_config'> {
    const draftConfig = goalDraft.scanner_config as ScannerConfig
    const scope =
        draftedExperiment ??
        (context
            ? {
                  experimentId: context.experiment.id as number,
                  variants: context.variantKey ? [context.variantKey] : null,
              }
            : null)
    if (!scope) {
        return { scanner_type: goalDraft.scanner_type as ScannerType, scanner_config: draftConfig } as Pick<
            ScannerFormValues,
            'scanner_type' | 'scanner_config'
        >
    }
    return {
        scanner_type: 'experiment',
        scanner_config: {
            prompt: draftConfig.prompt,
            length: ('length' in draftConfig && draftConfig.length) || 'medium',
            experiment_id: scope.experimentId,
            variants: scope.variants,
            balance_variants: true,
        },
    }
}

/** Without the experiment type, a drafted experiment scanner becomes the summarizer it is built on, and its
 * experiment moves to legacy targeting. */
function legacyDraftTypeAndConfig(
    goalDraft: DraftScannerResponseApi
): Pick<ScannerFormValues, 'scanner_type' | 'scanner_config'> {
    if (goalDraft.scanner_type !== 'experiment') {
        return {
            scanner_type: goalDraft.scanner_type as ScannerType,
            scanner_config: goalDraft.scanner_config as ScannerConfig,
        } as Pick<ScannerFormValues, 'scanner_type' | 'scanner_config'>
    }
    const config = goalDraft.scanner_config as ExperimentScannerConfig
    return { scanner_type: 'summarizer', scanner_config: { prompt: config.prompt, length: config.length ?? 'medium' } }
}

function omitQuery(scanner: ReplayScanner): Omit<ReplayScanner, 'query'> {
    const { query: _query, ...rest } = scanner
    return rest
}

function omitStamps(scanner: ReplayScanner): Omit<ReplayScanner, 'created_at' | 'updated_at' | 'last_swept_at'> {
    const { created_at: _created, updated_at: _updated, last_swept_at: _swept, ...rest } = scanner
    return rest
}

interface ObservationListParams {
    limit?: number
    offset?: number
    status?: string
    triggered_by?: string
    backfill_id?: string
    variant?: string
    watch_group?: string
    watch_category?: string
    verdict?: string
    tags?: string
    min_score?: number
    max_score?: number
    recording_subject?: string
    date_from?: string
    date_to?: string
    order_by?: string
}

export type ObservationsSorting = UrlSorting

const STATIC_ORDER_KEYS: Record<string, string> = {
    created_at: 'created_at',
    version: 'scanner_version',
    recording_subject: 'recording_subject_email',
    confidence: 'result_confidence',
}
// Only monitor and scorer have a JSONB-backed Result sort key on the server.
const RESULT_ORDER_KEY_BY_TYPE: Partial<Record<ScannerType, string>> = {
    scorer: 'result_score',
    monitor: 'result_verdict',
}

export function resolveOrderByKey(columnKey: string, scannerType: ScannerType | undefined): string | null {
    if (columnKey === 'result') {
        return (scannerType && RESULT_ORDER_KEY_BY_TYPE[scannerType]) ?? null
    }
    return STATIC_ORDER_KEYS[columnKey] ?? null
}

interface ObservationFilterValues {
    observationStatusFilter: ObservationStatusValue[]
    observationTriggeredByFilter: ObservationTriggeredByValue[]
    observationVerdictFilter: ObservationVerdictValue[]
    observationTagFilter: string[]
    observationMinScoreFilter: number | null
    observationMaxScoreFilter: number | null
    observationSubjectFilter: string
    observationDateFrom: string | null
    observationDateTo: string | null
    observationBackfillFilter: string | null
    observationVariantFilter: string | null
    observationWatchGroupFilter: string | null
    observationWatchCategoryFilter: string | null
}

type ObservationFilterParamKeys =
    | 'status'
    | 'triggered_by'
    | 'verdict'
    | 'tags'
    | 'min_score'
    | 'max_score'
    | 'recording_subject'
    | 'date_from'
    | 'date_to'
    | 'backfill_id'
    | 'variant'
    | 'watch_group'
    | 'watch_category'

/** The filter (non-pagination, non-sort) params shared by the list/stats endpoints and the URL query string. */
function observationFilterParams(
    values: ObservationFilterValues
): Pick<ObservationListParams, ObservationFilterParamKeys> {
    const params: Pick<ObservationListParams, ObservationFilterParamKeys> = {}
    if (values.observationStatusFilter.length > 0) {
        params.status = values.observationStatusFilter.join(',')
    }
    if (values.observationTriggeredByFilter.length > 0) {
        params.triggered_by = values.observationTriggeredByFilter.join(',')
    }
    if (values.observationVerdictFilter.length > 0) {
        params.verdict = values.observationVerdictFilter.join(',')
    }
    if (values.observationTagFilter.length > 0) {
        params.tags = values.observationTagFilter.join(',')
    }
    if (values.observationMinScoreFilter !== null) {
        params.min_score = values.observationMinScoreFilter
    }
    if (values.observationMaxScoreFilter !== null) {
        params.max_score = values.observationMaxScoreFilter
    }
    if (values.observationSubjectFilter.trim()) {
        params.recording_subject = values.observationSubjectFilter.trim()
    }
    if (values.observationDateFrom) {
        params.date_from = values.observationDateFrom
    }
    if (values.observationDateTo) {
        params.date_to = values.observationDateTo
    }
    if (values.observationBackfillFilter) {
        params.backfill_id = values.observationBackfillFilter
    }
    if (values.observationVariantFilter) {
        params.variant = values.observationVariantFilter
    }
    if (values.observationWatchGroupFilter) {
        params.watch_group = values.observationWatchGroupFilter
    }
    if (values.observationWatchCategoryFilter) {
        params.watch_category = values.observationWatchCategoryFilter
    }
    return params
}

/**
 * The observations table's filter + sort + page as URL query params. The scanner page's URL sync and
 * the observation detail links both build from this, so the view a reader returns to via "back" is by
 * construction the same one the list URL writes.
 */
export function observationListUrlParams(
    values: ObservationFilterValues & { observationsSort: ObservationsSorting | null; observationsPage: number }
): Record<string, string | number> {
    const params: Record<string, string | number> = { ...observationFilterParams(values) }
    const sort = serializeSortParam(values.observationsSort, DEFAULT_OBSERVATIONS_SORT)
    if (sort) {
        params.sort = sort
    }
    if (values.observationsPage > 1) {
        params.page = values.observationsPage
    }
    return params
}

/** Translate kea filter + sort state into the query params accepted by the list and stats endpoints. */
export function buildObservationListParams(
    values: ObservationFilterValues & {
        observationsSort: ObservationsSorting | null
        scanner: ReplayScanner | null
    },
    limit?: number,
    offset?: number
): ObservationListParams {
    const params: ObservationListParams = { ...observationFilterParams(values) }
    if (limit !== undefined) {
        params.limit = limit
    }
    if (offset !== undefined && offset > 0) {
        params.offset = offset
    }
    if (values.observationsSort) {
        const orderKey = resolveOrderByKey(values.observationsSort.columnKey, values.scanner?.scanner_type)
        if (orderKey) {
            params.order_by = values.observationsSort.order === -1 ? `-${orderKey}` : orderKey
        }
    }
    return params
}

// Multiplier applied to the forecast when seeding a fresh limit, so a limit set from the suggestion
// doesn't bind on ordinary month-to-month variance.
const CREDIT_LIMIT_SEED_HEADROOM = 2

export type CreditLimitUnit = 'credits' | 'observations'

export type GoalSpendMode = 'free' | 'budget'

// Prefills the typed budget at the free monthly credits (FREE_TIER_MONTHLY_CREDITS in backend/billing.py).
export const DEFAULT_GOAL_BUDGET = 2500

/** The spend a goal draft is sized to. The server sizes a free-only draft to the free credits it can spend. */
export type GoalDraftSpend = { freeOnly: true } | { monthlyCreditBudget: number }

export interface GoalDraftRequest {
    goal: string
    spend: GoalDraftSpend
    templateKey?: string
    experimentId?: number
}

/** Kept only when it is a slug the create API accepts, so a telemetry value can never block a save. */
function scannerEntryPoint(value: unknown): string | null {
    return typeof value === 'string' && /^[a-z0-9_]{1,64}$/.test(value) ? value : null
}

export interface GoalSpendChoice {
    mode: GoalSpendMode
    spend: GoalDraftSpend | null
    freeDisabledReason: string | null
}

/** One answer for the goal flow and the armed-goal draft, so neither drafts a free scanner with no free credits. */
export function goalSpendChoice(
    mode: GoalSpendMode,
    budgetInput: number | null,
    freeCreditsLeft: number | null
): GoalSpendChoice {
    const freeDisabledReason =
        freeCreditsLeft != null && freeCreditsLeft <= 0
            ? 'Your organization has used its free credits for this billing period'
            : null
    const effectiveMode = freeDisabledReason ? 'budget' : mode
    return {
        mode: effectiveMode,
        spend:
            effectiveMode === 'free'
                ? { freeOnly: true }
                : budgetInput != null
                  ? { monthlyCreditBudget: budgetInput }
                  : null,
        freeDisabledReason,
    }
}

// Admission needs the full price of a scan, so a remainder under one price admits nothing.
export function creditsToObservations(credits: number, creditsPerObservation: number): number {
    return Math.floor(credits / creditsPerObservation)
}

export function observationsToCredits(observations: number, creditsPerObservation: number): number {
    return Math.min(observations * creditsPerObservation, MAX_CREDIT_LIMIT)
}

export interface CreditLimitState {
    /** The limit in credits, or null when the field is empty or the limit is off. */
    limit: number | null
    unit: CreditLimitUnit
    observationLimit: number | null
    isOn: boolean
    estimatedMonthly: number | null
    estimatedMonthlyObservations: number | null
    creditsPerObservation: number | null
    isBelowEstimate: boolean
    cannotAffordOneScan: boolean
    /** What to put in the field when the user switches the limit on; null leaves it empty. */
    seedValue: number | null
}

/** The fields a free-only change moves, copied from the saved scanner so the status updates without a reload. */
function freeOnlyFields(
    saved: ReplayScannerApi
): Pick<ReplayScannerApi, 'free_only' | 'limit_reached' | 'limit_from_free_credits' | 'credits_used_against_limit'> {
    return {
        free_only: saved.free_only,
        limit_reached: saved.limit_reached,
        limit_from_free_credits: saved.limit_from_free_credits,
        credits_used_against_limit: saved.credits_used_against_limit,
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayScannerLogicValues {
    affectedCohort: {
        cohort_id: number
    } | null
    affectedCohortLoading: boolean
    availableTags: string[]
    chartDateFrom: string | null
    chartDateTo: string | null
    copyingAllObservations: boolean
    creationMethod: ScannerCreationMethodEnumApi
    creditLimitState: CreditLimitState
    creditLimitUnit: CreditLimitUnit
    durationValidationError: string | null
    entryPoint: string | null
    estimateRequestVersion: number
    experimentContext: ExperimentScannerContext | null
    experimentContextLinked: boolean
    goalBudgetInput: number | null
    goalDraft: DraftScannerResponseApi | null
    goalDraftInput: string
    goalDraftLoading: boolean
    goalDraftQuery: RecordingsQuery | null
    goalExperiment: ExperimentBasicApi | null
    goalSpendMode: GoalSpendMode
    hasActiveObservationFilters: boolean
    hasObservationsInFlight: boolean
    hasUnsavedChanges: boolean
    isNew: boolean
    isScannerSubmitting: boolean
    isScannerValid: boolean
    linkedExperimentContext: ExperimentScannerContext | null
    lockedToExperimentScanner: boolean
    observationBackfillFilter: string | null
    observationDateFrom: string | null
    observationDateTo: string | null
    observationDetailLinkParams: Record<string, number | string>
    observationMaxScoreFilter: number | null
    observationMinScoreFilter: number | null
    observationStats: ObservationStatusStats
    observationStatsApi: ObservationStatsApi | null
    observationStatsApiLoading: boolean
    observationStatusFilter: ObservationStatusValue[]
    observationSubjectFilter: string
    observationTagFilter: string[]
    observationTriggeredByFilter: ObservationTriggeredByValue[]
    observationVariantFilter: string | null
    observationVerdictFilter: ObservationVerdictValue[]
    observationWatchCategoryFilter: string | null
    observationWatchGroupFilter: string | null
    observations: ReplayObservationApi[]
    observationsActive: boolean
    observationsLoading: boolean
    observationsPage: number
    observationsSort: ObservationsSorting | null
    observationsTotal: number
    onDemandObservationSuccessCount: number
    originalScanner: ScannerFormValues | null
    pollUntil: number
    retryingObservationIds: string[]
    savingCohortKey: string | null
    scanner: ScannerFormValues
    scannerAllErrors: Record<string, any>
    scannerChanged: boolean
    scannerDraftSavedAt: number | null
    scannerErrors: DeepPartialMap<ScannerFormValues, ValidationErrorType>
    scannerEstimate: EstimateResponseApi | null
    scannerEstimateError: string | null
    scannerEstimateLoading: boolean
    scannerHasErrors: boolean
    scannerLoading: boolean
    scannerManualErrors: Record<string, any>
    scannerTouched: boolean
    scannerTouches: Record<string, boolean>
    scannerValidationErrors: DeepPartialMap<ScannerFormValues, ValidationErrorType>
    showScannerErrors: boolean
    sidePanelContext: SidePanelSceneContext | null
    stepErrors: Partial<Record<ScannerEditorStep, string[]>>
    togglingEnabled: boolean
    triggeringOnDemandObservation: boolean
    turningOffFreeOnly: boolean
    turningOnSelfDriving: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayScannerLogicActions {
    clearClassifierTags: () => {
        value: true
    }
    clearObservationFilters: () => {
        value: true
    }
    copyAllObservations: () => {
        value: true
    }
    copyAllObservationsFinished: () => {
        value: true
    }
    detachExperimentContext: () => {
        value: true
    }
    discardScannerDraft: () => {
        value: true
    }
    draftScannerFromGoal: (request: GoalDraftRequest) => {
        request: GoalDraftRequest
    }
    draftScannerFromGoalFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    draftScannerFromGoalSuccess: (
        goalDraft: DraftScannerResponseApi | null,
        payload?: {
            request: GoalDraftRequest
        }
    ) => {
        goalDraft: DraftScannerResponseApi | null
        payload?: {
            request: GoalDraftRequest
        }
    }
    linkExperimentContext: (context: ExperimentScannerContext) => {
        context: ExperimentScannerContext
    }
    loadObservationStats: () => {
        value: true
    }
    loadObservationStatsFailure: () => {
        value: true
    }
    loadObservationStatsSuccess: (stats: ObservationStatsApi) => {
        stats: ObservationStatsApi
    }
    loadObservations: (background?: any) => {
        background: any
    }
    loadObservationsFailure: () => {
        value: true
    }
    loadObservationsSuccess: (
        observations: ReplayObservationApi[],
        total: number
    ) => {
        observations: ReplayObservationApi[]
        total: number
    }
    loadScanner: () => {
        value: true
    }
    loadScannerEstimate: () => {
        value: true
    }
    loadScannerEstimateFailure: (error?: string | null) => {
        error: string | null
    }
    loadScannerEstimateSuccess: (estimate: EstimateResponseApi) => {
        estimate: EstimateResponseApi
    }
    loadScannerFailure: () => {
        value: true
    }
    loadScannerSuccess: (scanner: ScannerFormValues) => {
        scanner: ScannerFormValues
    }
    rebuildExperimentContext: (linkedExperimentId?: number | null) => {
        linkedExperimentId: number | null
    }
    refreshObservations: () => {
        value: true
    }
    requestScannerEstimate: () => {
        value: true
    }
    resetScanner: (values?: ScannerFormValues) => {
        values?: ScannerFormValues
    }
    restoreObservationsTableState: (state: {
        backfillId: string | null
        dateFrom: string | null
        dateTo: string | null
        maxScore: number | null
        minScore: number | null
        page: number
        sort: ObservationsSorting | null
        status: ObservationStatusValue[]
        subject: string
        tags: string[]
        triggeredBy: ObservationTriggeredByValue[]
        variant: string | null
        verdict: ObservationVerdictValue[]
        watchCategory: string | null
        watchGroup: string | null
    }) => {
        backfillId: string | null
        dateFrom: string | null
        dateTo: string | null
        maxScore: number | null
        minScore: number | null
        page: number
        sort: ObservationsSorting | null
        status: ObservationStatusEnumApi[]
        subject: string
        tags: string[]
        triggeredBy: ObservationTriggerEnumApi[]
        variant: string | null
        verdict: ObservationVerdictValue[]
        watchCategory: string | null
        watchGroup: string | null
    }
    retryObservation: (observationId: string) => {
        observationId: string
    }
    retryObservationFailure: (observationId: string) => {
        observationId: string
    }
    retryObservationSuccess: (observationId: string) => {
        observationId: string
    }
    saveAffectedCohort: (
        windowDays: number,
        qualifier?: AffectedCohortQualifier
    ) => {
        qualifier: AffectedCohortQualifier
        windowDays: number
    }
    saveAffectedCohortFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    saveAffectedCohortSuccess: (
        affectedCohort: {
            cohort_id: number
        } | null,
        payload?: {
            qualifier: AffectedCohortQualifier
            windowDays: number
        }
    ) => {
        affectedCohort: {
            cohort_id: number
        } | null
        payload?: {
            qualifier: AffectedCohortQualifier
            windowDays: number
        }
    }
    scannerDashboardLinked: (dashboardId: number) => {
        dashboardId: number
    }
    scannerSaved: (scanner: ScannerFormValues) => {
        scanner: ScannerFormValues
    }
    scannerWatermarkRefreshed: (scanner: ReplayScanner) => {
        scanner: ReplayScanner
    }
    setChartDateRange: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
    setCreditLimitUnit: (unit: CreditLimitUnit) => {
        unit: CreditLimitUnit
    }
    setEntryPoint: (entryPoint: string | null) => {
        entryPoint: string | null
    }
    setExperimentContext: (context: ExperimentScannerContext | null) => {
        context: ExperimentScannerContext | null
    }
    setExperimentVariant: (variantKey: string | null) => {
        variantKey: string | null
    }
    setGoalBudgetInput: (budget: number | null) => {
        budget: number | null
    }
    setGoalDraftInput: (goal: string) => {
        goal: string
    }
    setGoalDraftQuery: (query: RecordingsQuery | null) => {
        query: RecordingsQuery | null
    }
    setGoalExperiment: (experiment: ExperimentBasicApi | null) => {
        experiment: ExperimentBasicApi | null
    }
    setGoalSpendMode: (mode: GoalSpendMode) => {
        mode: GoalSpendMode
    }
    setObservationBackfillFilter: (value: string | null) => {
        value: string | null
    }
    setObservationDateRange: (
        dateFrom: string | null,
        dateTo: string | null
    ) => {
        dateFrom: string | null
        dateTo: string | null
    }
    setObservationScoreRange: (
        minScore: number | null,
        maxScore: number | null
    ) => {
        maxScore: number | null
        minScore: number | null
    }
    setObservationStatusFilter: (values: ObservationStatusValue[]) => {
        values: ObservationStatusEnumApi[]
    }
    setObservationSubjectFilter: (value: string) => {
        value: string
    }
    setObservationTagFilter: (values: string[]) => {
        values: string[]
    }
    setObservationTriggeredByFilter: (values: ObservationTriggeredByValue[]) => {
        values: ObservationTriggerEnumApi[]
    }
    setObservationVariantFilter: (value: string | null) => {
        value: string | null
    }
    setObservationVerdictFilter: (values: ObservationVerdictValue[]) => {
        values: ObservationVerdictValue[]
    }
    setObservationWatchGroupFilter: (value: string | null) => {
        value: string | null
    }
    setObservationsActive: (active: boolean) => {
        active: boolean
    }
    setObservationsPage: (page: number) => {
        page: number
    }
    setObservationsSort: (sorting: ObservationsSorting | null) => {
        sorting: ObservationsSorting | null
    }
    setScannerDraftSavedAt: (savedAt: number | null) => {
        savedAt: number | null
    }
    setScannerExperiment: (experimentId: number | null) => {
        experimentId: number | null
    }
    setScannerManualErrors: (errors: Record<string, any>) => {
        errors: Record<string, any>
    }
    setScannerType: (scannerType: ScannerType) => {
        scannerType: ScannerTypeEnumApi
    }
    setScannerValue: (
        key: FieldName,
        value: any
    ) => {
        name: FieldName
        value: any
    }
    setScannerValues: (values: DeepPartial<ScannerFormValues>) => {
        values: DeepPartial<ScannerFormValues>
    }
    startFromScratch: () => {
        value: true
    }
    submitScanner: () => {
        value: boolean
    }
    submitScannerFailure: (
        error: Error,
        errors: Record<string, any>
    ) => {
        error: Error
        errors: Record<string, any>
    }
    submitScannerRequest: (scanner: ScannerFormValues) => {
        scanner: ScannerFormValues
    }
    submitScannerSuccess: (scanner: ScannerFormValues) => {
        scanner: ScannerFormValues
    }
    toggleEnabled: () => {
        value: true
    }
    toggleEnabledFailure: () => {
        value: true
    }
    toggleEnabledSuccess: (enabled: boolean) => {
        enabled: boolean
    }
    touchScannerField: (key: string) => {
        key: string
    }
    triggerOnDemandObservation: (
        sessionId: string,
        silent?: any
    ) => {
        sessionId: string
        silent: any
    }
    triggerOnDemandObservationFailure: () => {
        value: true
    }
    triggerOnDemandObservationSuccess: () => {
        value: true
    }
    turnOffFreeOnly: () => {
        value: true
    }
    turnOffFreeOnlyFailure: () => {
        value: true
    }
    turnOffFreeOnlySuccess: (saved: ReplayScannerApi) => {
        saved: ReplayScannerApi
    }
    turnOnSelfDriving: () => {
        value: true
    }
    turnOnSelfDrivingFailure: () => {
        value: true
    }
    turnOnSelfDrivingSuccess: (
        scannerVersion: number,
        updatedAt: string
    ) => {
        scannerVersion: number
        updatedAt: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayScannerLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isNew: (id: string) => boolean
        durationValidationError: (scanner: ScannerFormValues) => string | null
        stepErrors: (
            showScannerErrors: boolean,
            scannerValidationErrors: DeepPartialMap<ScannerFormValues, ValidationErrorType>,
            durationValidationError: string | null
        ) => Partial<Record<ScannerEditorStep, string[]>>
        linkedExperimentContext: (
            experimentContext: ExperimentScannerContext | null,
            experimentContextLinked: boolean
        ) => ExperimentScannerContext | null
        lockedToExperimentScanner: (
            linkedExperimentContext: ExperimentScannerContext | null,
            scanner: ScannerFormValues
        ) => boolean
        hasUnsavedChanges: (scanner: ScannerFormValues, originalScanner: ScannerFormValues | null) => boolean
        hasObservationsInFlight: (observationStatsApi: ObservationStatsApi | null) => boolean
        hasActiveObservationFilters: (
            observationStatusFilter: ObservationStatusEnumApi[],
            observationTriggeredByFilter: ObservationTriggerEnumApi[],
            observationVerdictFilter: ObservationVerdictValue[],
            observationTagFilter: string[],
            observationMinScoreFilter: number | null,
            observationMaxScoreFilter: number | null,
            observationSubjectFilter: string,
            observationDateFrom: string | null,
            observationDateTo: string | null,
            observationBackfillFilter: string | null,
            observationVariantFilter: string | null,
            observationWatchGroupFilter: string | null
        ) => boolean
        observationDetailLinkParams: (
            observationsPage: number,
            observationStatusFilter: ObservationStatusEnumApi[],
            observationTriggeredByFilter: ObservationTriggerEnumApi[],
            observationVerdictFilter: ObservationVerdictValue[],
            observationTagFilter: string[],
            observationMinScoreFilter: number | null,
            observationMaxScoreFilter: number | null,
            observationSubjectFilter: string,
            observationDateFrom: string | null,
            observationDateTo: string | null,
            observationBackfillFilter: string | null,
            observationVariantFilter: string | null,
            observationWatchGroupFilter: string | null,
            observationWatchCategoryFilter: string | null,
            observationsSort: ObservationsSorting | null,
            scanner: ScannerFormValues
        ) => Record<string, number | string>
        availableTags: (observationStatsApi: ObservationStatsApi | null) => string[]
        observationStats: (observationStatsApi: ObservationStatsApi | null) => ObservationStatusStats
        sidePanelContext: (scanner: ScannerFormValues, isNew: boolean) => SidePanelSceneContext | null
        creditLimitState: (
            scanner: ScannerFormValues,
            scannerEstimate: EstimateResponseApi | null,
            scannerEstimateLoading: boolean,
            creditLimitUnit: CreditLimitUnit
        ) => CreditLimitState
    }
}

export type replayScannerLogicType = MakeLogicType<
    replayScannerLogicValues,
    replayScannerLogicActions,
    ReplayScannerLogicProps,
    replayScannerLogicMeta
>

export const replayScannerLogic = kea<replayScannerLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerLogic']),
    props({} as ReplayScannerLogicProps),
    key((props) => props.id),

    actions({
        setObservationsActive: (active: boolean) => ({ active }),
        setCreditLimitUnit: (unit: CreditLimitUnit) => ({ unit }),
        loadScanner: true,
        loadScannerSuccess: (scanner: ScannerFormValues) => ({ scanner }),
        loadScannerFailure: true,
        // Background refetches use this instead of loadScannerSuccess, which also resets the form,
        // originalScanner, and submitIntent, and can refire the observation loads.
        scannerWatermarkRefreshed: (scanner: ReplayScanner) => ({ scanner }),
        setExperimentContext: (context: ExperimentScannerContext | null) => ({ context }),
        // The context of an experiment the wizard was entered from, as opposed to one picked in the editor.
        linkExperimentContext: (context: ExperimentScannerContext) => ({ context }),
        setExperimentVariant: (variantKey: string | null) => ({ variantKey }),
        setScannerExperiment: (experimentId: number | null) => ({ experimentId }),
        detachExperimentContext: true,
        // Pass the experiment the wizard was entered from to restore that link with the context.
        rebuildExperimentContext: (linkedExperimentId: number | null = null) => ({ linkedExperimentId }),
        saveAffectedCohort: (windowDays: number, qualifier: AffectedCohortQualifier = {}) => ({
            windowDays,
            qualifier,
        }),
        setScannerType: (scannerType: ScannerType) => ({ scannerType }),
        startFromScratch: true,
        discardScannerDraft: true,
        setScannerDraftSavedAt: (savedAt: number | null) => ({ savedAt }),
        // Fired only after an actual API write, unlike submitScannerSuccess (which the advance path emits too).
        scannerSaved: (scanner: ScannerFormValues) => ({ scanner }),
        clearClassifierTags: true,
        draftScannerFromGoal: (request: GoalDraftRequest) => ({ request }),
        setGoalDraftInput: (goal: string) => ({ goal }),
        setGoalExperiment: (experiment: ExperimentBasicApi | null) => ({ experiment }),
        setGoalBudgetInput: (budget: number | null) => ({ budget }),
        setGoalSpendMode: (mode: GoalSpendMode) => ({ mode }),
        setGoalDraftQuery: (query: RecordingsQuery | null) => ({ query }),
        setEntryPoint: (entryPoint: string | null) => ({ entryPoint }),
        loadObservations: (background = false) => ({ background }),
        loadObservationsSuccess: (observations: ReplayObservationApi[], total: number) => ({ observations, total }),
        loadObservationsFailure: true,
        setObservationsPage: (page: number) => ({ page }),
        setObservationsSort: (sorting: ObservationsSorting | null) => ({ sorting }),
        loadObservationStats: true,
        loadObservationStatsSuccess: (stats: ObservationStatsApi) => ({ stats }),
        loadObservationStatsFailure: true,
        toggleEnabled: true,
        toggleEnabledSuccess: (enabled: boolean) => ({ enabled }),
        toggleEnabledFailure: true,
        turnOffFreeOnly: true,
        turnOffFreeOnlySuccess: (saved: ReplayScannerApi) => ({ saved }),
        turnOffFreeOnlyFailure: true,
        turnOnSelfDriving: true,
        turnOnSelfDrivingSuccess: (scannerVersion: number, updatedAt: string) => ({ scannerVersion, updatedAt }),
        scannerDashboardLinked: (dashboardId: number) => ({ dashboardId }),
        turnOnSelfDrivingFailure: true,
        setObservationStatusFilter: (values: ObservationStatusValue[]) => ({ values }),
        setObservationTriggeredByFilter: (values: ObservationTriggeredByValue[]) => ({ values }),
        setObservationVerdictFilter: (values: ObservationVerdictValue[]) => ({ values }),
        setObservationTagFilter: (values: string[]) => ({ values }),
        setObservationScoreRange: (minScore: number | null, maxScore: number | null) => ({ minScore, maxScore }),
        setObservationSubjectFilter: (value: string) => ({ value }),
        setObservationDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setObservationBackfillFilter: (value: string | null) => ({ value }),
        setObservationVariantFilter: (value: string | null) => ({ value }),
        setObservationWatchGroupFilter: (value: string | null) => ({ value }),
        clearObservationFilters: true,
        restoreObservationsTableState: (state: {
            page: number
            sort: ObservationsSorting | null
            status: ObservationStatusValue[]
            triggeredBy: ObservationTriggeredByValue[]
            verdict: ObservationVerdictValue[]
            tags: string[]
            minScore: number | null
            maxScore: number | null
            subject: string
            dateFrom: string | null
            dateTo: string | null
            backfillId: string | null
            variant: string | null
            watchGroup: string | null
            watchCategory: string | null
        }) => state,
        setChartDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        requestScannerEstimate: true,
        loadScannerEstimate: true,
        loadScannerEstimateSuccess: (estimate: EstimateResponseApi) => ({ estimate }),
        loadScannerEstimateFailure: (error: string | null = null) => ({ error }),
        // `silent` skips the success toast — the list view has its own inline spinner/result feedback.
        triggerOnDemandObservation: (sessionId: string, silent = false) => ({ sessionId, silent }),
        triggerOnDemandObservationSuccess: true,
        triggerOnDemandObservationFailure: true,
        retryObservation: (observationId: string) => ({ observationId }),
        retryObservationSuccess: (observationId: string) => ({ observationId }),
        retryObservationFailure: (observationId: string) => ({ observationId }),
        refreshObservations: true,
        copyAllObservations: true,
        copyAllObservationsFinished: true,
    }),

    forms(({ props, actions, values }) => ({
        scanner: {
            defaults: newScanner(teamLogic.findMounted()?.values.currentTeam?.name),
            errors: (scanner: ScannerFormValues) => {
                // API-loaded scanners never carry the UI-only toggle, so fall back to whether a limit is set.
                const creditLimitEnabled = scanner.credit_limit_enabled ?? scanner.credit_limit != null
                const configErrors: Record<string, string | undefined> = {}
                if (!scanner.scanner_config?.prompt?.trim()) {
                    configErrors.prompt = 'Prompt is required'
                }
                if (scanner.scanner_type === 'classifier') {
                    const tags = scanner.scanner_config.tags ?? []
                    if (tags.length === 0) {
                        configErrors.tags = 'Add at least one category'
                    } else if (tags.some((t) => !t.trim())) {
                        configErrors.tags = "Categories can't be blank"
                    } else if (new Set(tags.map((t) => t.trim().toLowerCase())).size !== tags.length) {
                        configErrors.tags = 'Categories must be unique'
                    }
                }
                if (scanner.scanner_type === 'experiment' && !scanner.scanner_config.experiment_id) {
                    configErrors.experiment_id = 'Pick an experiment'
                }
                if (scanner.scanner_type === 'scorer') {
                    const { min, max } = scanner.scanner_config.scale
                    if (
                        typeof min !== 'number' ||
                        typeof max !== 'number' ||
                        !Number.isFinite(min) ||
                        !Number.isFinite(max)
                    ) {
                        configErrors.scale = 'Scale min and max must be numbers'
                    } else if (min >= max) {
                        configErrors.scale = 'Scale max must be greater than min'
                    }
                }
                return {
                    sampling_rate:
                        scanner.sampling_rate > 0 && scanner.sampling_rate <= 1
                            ? undefined
                            : 'Sampling rate must be between 0% and 100%',
                    credit_limit:
                        creditLimitEnabled && scanner.credit_limit == null
                            ? // The toggle is on with an empty field. Block the save rather than silently saving as unlimited.
                              'Enter a limit, or turn the limit off'
                            : scanner.credit_limit == null ||
                                (Number.isInteger(scanner.credit_limit) &&
                                    scanner.credit_limit >= 1 &&
                                    scanner.credit_limit <= MAX_CREDIT_LIMIT)
                              ? undefined
                              : `The limit must be a whole number of credits between 1 and ${MAX_CREDIT_LIMIT.toLocaleString()}`,
                    scanner_config: Object.keys(configErrors).length > 0 ? configErrors : undefined,
                }
            },
            submit: async (scanner: ScannerFormValues) => {
                // A non-final step only ever offers "Next", so any submit there advances rather than persisting.
                // Enter would otherwise save an existing scanner and leave the wizard from the middle of it.
                const editor = scannerEditorSceneLogic.findMounted()
                const currentStep = editor?.values.step ?? 'configure'
                // The overview step sits outside the manual wizard's step list, so its submit must
                // persist rather than resolve to the list's first step and navigate there.
                const nextStep = nextScannerEditorStep(currentStep, editor?.values.steps ?? scannerEditorSteps(false))
                if (nextStep) {
                    router.actions.push(scannerStepUrlWithParams(nextStep, props.id, router.values.searchParams))
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                // credit_limit_enabled is UI-only form state; the API payload carries only credit_limit itself.
                const { credit_limit_enabled: _creditLimitEnabled, ...rest } = scanner
                // The name is optional in the UI but required by the API, so an emptied one falls back.
                const apiScanner = {
                    ...rest,
                    name:
                        rest.name?.trim() || defaultScannerName(teamLogic.values.currentTeam?.name, rest.scanner_type),
                }
                const body = apiScanner.query == null ? omitQuery(apiScanner) : apiScanner
                try {
                    if (props.id === 'new') {
                        // Telemetry only, and only on create: the API reports it and drops it, so a
                        // saved scanner can be attributed to how it was built. An edit says nothing
                        // about that, so the update payload below leaves it out.
                        const response = await visionScannersCreate(
                            String(teamId),
                            scannerToApiBody({
                                ...body,
                                creation_method: values.creationMethod,
                                entry_point: values.entryPoint,
                            })
                        )
                        actions.scannerSaved(scanner)
                        leaveScannerEditor(props.id, urls.replayVision(response.id))
                        // First scheduled results are minutes away, so the copy matches the Overview's
                        // pending panel and the button hands off to the instant on-demand tab.
                        lemonToast.success('Scanner created. First scan in progress.', {
                            button: {
                                label: 'Scan a recording now',
                                action: () => router.actions.push(`${urls.replayVision(response.id)}?tab=run`),
                                dataAttr: 'vision-scanner-created-scan-now',
                            },
                        })
                    } else {
                        await visionScannersPartialUpdate(String(teamId), props.id, scannerToPatchedApiBody(body))
                        actions.scannerSaved(scanner)
                        lemonToast.success('Scanner saved')
                        leaveScannerEditor(props.id, urls.replayVision(props.id))
                    }
                } catch (error: any) {
                    // A duplicate name is the one field error the details step can fix, so route back to it.
                    if (error.attr === 'name' && error.detail) {
                        actions.setScannerManualErrors({ name: error.detail })
                        // From the goal overview, mark the trip so the details step returns there after the fix.
                        router.actions.push(
                            scannerStepUrlWithParams(
                                'details',
                                props.id,
                                currentStep === 'overview'
                                    ? { ...router.values.searchParams, from: 'overview' }
                                    : router.values.searchParams
                            )
                        )
                        lemonToast.error(error.detail)
                        throw error
                    }
                    lemonToast.error(`Failed to save scanner${error.detail ? `: ${error.detail}` : ''}`)
                    throw error
                }
            },
        },
    })),

    loaders(({ props, values }) => ({
        affectedCohort: [
            null as { cohort_id: number } | null,
            {
                saveAffectedCohort: async ({ windowDays, qualifier }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || props.id === 'new') {
                        return values.affectedCohort
                    }
                    try {
                        const response = await visionScannersAffectedCohortCreate(String(teamId), props.id, {
                            window_days: windowDays,
                            ...qualifier,
                        })
                        lemonToast.success(
                            `Cohort "${response.name}" created with ${response.users_in_cohort.toLocaleString()} ${
                                response.users_in_cohort === 1 ? 'person' : 'people'
                            }`,
                            {
                                button: {
                                    label: 'View cohort',
                                    action: () => router.actions.push(urls.cohort(response.cohort_id)),
                                },
                            }
                        )
                        return { cohort_id: response.cohort_id }
                    } catch (error: any) {
                        lemonToast.error(`Failed to create cohort${error?.detail ? `: ${error.detail}` : ''}`)
                        return values.affectedCohort
                    }
                },
            },
        ],
        goalDraft: [
            null as DraftScannerResponseApi | null,
            {
                // Errors surface through draftScannerFromGoalFailure; kea-loaders dispatches it for us.
                draftScannerFromGoal: async ({ request: { goal, spend, experimentId } }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || !goal.trim()) {
                        return values.goalDraft
                    }
                    return await visionScannersDraftCreate(String(teamId), {
                        goal: goal.trim(),
                        // The server sizes a free-only draft to the free credits itself.
                        ...('freeOnly' in spend
                            ? { free_only: true }
                            : { monthly_credit_budget: spend.monthlyCreditBudget }),
                        experiment_id: experimentId,
                        ...(values.goalDraftQuery ? { query: values.goalDraftQuery } : {}),
                    })
                },
            },
        ],
    })),

    reducers({
        observationsActive: [false, { setObservationsActive: (_, { active }) => active }],
        // UI-only: the API stores every limit in credits, so a reopened scanner shows credits again.
        creditLimitUnit: [
            'credits' as CreditLimitUnit,
            {
                setCreditLimitUnit: (_, { unit }) => unit,
                startFromScratch: () => 'credits',
                discardScannerDraft: () => 'credits',
            },
        ],
        scannerDraftSavedAt: [
            null as number | null,
            {
                setScannerDraftSavedAt: (_, { savedAt }) => savedAt,
            },
        ],
        goalDraftInput: [
            '',
            {
                setGoalDraftInput: (_, { goal }) => goal,
                // Kept through a successful draft so "Start over" on the review step returns with the goal
                // still there to edit. Starting from scratch, a discard, or a save ends that goal.
                startFromScratch: () => '',
                discardScannerDraft: () => '',
                scannerSaved: () => '',
            },
        ],
        // Picked from the goal flow's experiment starter, and sent with the goal even after the goal is edited.
        goalExperiment: [
            null as ExperimentBasicApi | null,
            {
                setGoalExperiment: (_, { experiment }) => experiment,
                startFromScratch: () => null,
                discardScannerDraft: () => null,
                scannerSaved: () => null,
            },
        ],
        // The monthly credit budget input on the goal-based creation flow, used when the person sets a budget.
        goalBudgetInput: [
            DEFAULT_GOAL_BUDGET as number | null,
            {
                setGoalBudgetInput: (_, { budget }) => budget,
            },
        ],
        goalSpendMode: [
            'free' as GoalSpendMode,
            {
                setGoalSpendMode: (_, { mode }) => mode,
            },
        ],
        // Kept through a failed draft, so a retry from the goal page still watches the chosen recordings.
        goalDraftQuery: [
            null as RecordingsQuery | null,
            {
                setGoalDraftQuery: (_, { query }) => query,
                startFromScratch: () => null,
                discardScannerDraft: () => null,
                scannerSaved: () => null,
            },
        ],
        // Kept through a path switch, because a person who builds by hand after the AI flow still started there.
        entryPoint: [
            null as string | null,
            {
                setEntryPoint: (_, { entryPoint }) => entryPoint,
                discardScannerDraft: () => null,
                scannerSaved: () => null,
            },
        ],
        // Starting from scratch replaces the drafted form, so its rationale no longer describes the config.
        goalDraft: [
            null as DraftScannerResponseApi | null,
            {
                startFromScratch: () => null,
            },
        ],
        // How the form standing in front of the user was built, sent with the create request so the
        // saved scanner can be attributed. Last path taken wins, because each of these replaces the
        // form: someone who drafts with AI and then starts from scratch saved a hand-built scanner.
        creationMethod: [
            'scratch' as ScannerCreationMethodEnumApi,
            {
                draftScannerFromGoal: () => 'ai' as ScannerCreationMethodEnumApi,
                startFromScratch: () => 'scratch' as ScannerCreationMethodEnumApi,
            },
        ],
        savingCohortKey: [
            null as string | null,
            {
                saveAffectedCohort: (_, { qualifier }) => qualifier.verdict ?? qualifier.tag ?? null,
                saveAffectedCohortSuccess: () => null,
                saveAffectedCohortFailure: () => null,
            },
        ],
        scanner: {
            // Only the sweep watermark lands, so a background refresh can't clobber unsaved form edits.
            scannerWatermarkRefreshed: (state: ReplayScanner, { scanner }: { scanner: ReplayScanner }) =>
                state ? { ...state, last_swept_at: scanner.last_swept_at } : scanner,
            scannerDashboardLinked: (state: ReplayScanner, { dashboardId }: { dashboardId: number }) =>
                state ? { ...state, dashboard_id: dashboardId, dashboard_suggested: false } : state,
        },
        experimentContext: [
            null as ExperimentScannerContext | null,
            {
                setExperimentContext: (_, { context }) => context,
                linkExperimentContext: (_, { context }) => context,
                setExperimentVariant: (state, { variantKey }) => (state ? { ...state, variantKey } : state),
                detachExperimentContext: () => null,
            },
        ],
        // Only an experiment the wizard was entered from carries into a new start. One picked in the
        // editor belongs to that scanner, so a starting point clicked later must not inherit it.
        experimentContextLinked: [
            false,
            {
                linkExperimentContext: () => true,
                setExperimentContext: () => false,
                detachExperimentContext: () => false,
            },
        ],
        originalScanner: [
            null as ScannerFormValues | null,
            {
                loadScannerSuccess: (_, { scanner }) => scanner,
                // Keyed on the real save, not submitScannerSuccess — kea-forms fires that on the no-API advance path too.
                scannerSaved: (_, { scanner }) => scanner,
                toggleEnabledSuccess: (state, { enabled }) => (state ? { ...state, enabled } : state),
                turnOffFreeOnlySuccess: (state, { saved }) => (state ? { ...state, ...freeOnlyFields(saved) } : state),
                // Self-driving changes the prompt the model gets, so the backend bumps the version with it.
                turnOnSelfDrivingSuccess: (state, { scannerVersion, updatedAt }) =>
                    state
                        ? { ...state, emits_signals: true, scanner_version: scannerVersion, updated_at: updatedAt }
                        : state,
                // Mirrors the `scanner` patch so linking a dashboard never leaves the form looking edited.
                scannerDashboardLinked: (state, { dashboardId }) =>
                    state ? { ...state, dashboard_id: dashboardId, dashboard_suggested: false } : state,
            },
        ],
        togglingEnabled: [
            false,
            {
                toggleEnabled: () => true,
                toggleEnabledSuccess: () => false,
                toggleEnabledFailure: () => false,
            },
        ],
        turningOffFreeOnly: [
            false,
            {
                turnOffFreeOnly: () => true,
                turnOffFreeOnlySuccess: () => false,
                turnOffFreeOnlyFailure: () => false,
            },
        ],
        turningOnSelfDriving: [
            false,
            {
                turnOnSelfDriving: () => true,
                turnOnSelfDrivingSuccess: () => false,
                turnOnSelfDrivingFailure: () => false,
            },
        ],
        triggeringOnDemandObservation: [
            false,
            {
                triggerOnDemandObservation: () => true,
                triggerOnDemandObservationSuccess: () => false,
                triggerOnDemandObservationFailure: () => false,
            },
        ],
        copyingAllObservations: [
            false,
            {
                copyAllObservations: () => true,
                copyAllObservationsFinished: () => false,
            },
        ],
        onDemandObservationSuccessCount: [
            0,
            {
                triggerOnDemandObservationSuccess: (state: number) => state + 1,
            },
        ],
        pollUntil: [
            0,
            {
                triggerOnDemandObservationSuccess: () => Date.now() + OBSERVE_POLL_GRACE_MS,
                // The replacement row is inserted by the workflow moments after the retry 202 lands.
                retryObservationSuccess: () => Date.now() + OBSERVE_POLL_GRACE_MS,
            },
        ],
        retryingObservationIds: [
            [] as string[],
            {
                retryObservation: (state: string[], { observationId }: { observationId: string }) => [
                    ...state,
                    observationId,
                ],
                retryObservationSuccess: (state: string[], { observationId }: { observationId: string }) =>
                    state.filter((id) => id !== observationId),
                retryObservationFailure: (state: string[], { observationId }: { observationId: string }) =>
                    state.filter((id) => id !== observationId),
            },
        ],
        scannerLoading: [
            false,
            {
                loadScanner: () => true,
                loadScannerSuccess: () => false,
                loadScannerFailure: () => false,
            },
        ],
        observations: [
            [] as ReplayObservationApi[],
            {
                loadObservationsSuccess: (_, { observations }) => observations,
            },
        ],
        observationsTotal: [
            0,
            {
                loadObservationsSuccess: (_, { total }) => total,
            },
        ],
        observationsPage: [
            1,
            {
                setObservationsPage: (_, { page }) => Math.max(1, page),
                // Filter / sort changes can shift rows around so the current page may no longer make sense; reset.
                setObservationStatusFilter: () => 1,
                setObservationTriggeredByFilter: () => 1,
                setObservationVerdictFilter: () => 1,
                setObservationTagFilter: () => 1,
                setObservationScoreRange: () => 1,
                setObservationSubjectFilter: () => 1,
                setObservationDateRange: () => 1,
                setObservationsSort: () => 1,
                clearObservationFilters: () => 1,
                restoreObservationsTableState: (_, { page }) => Math.max(1, page),
            },
        ],
        observationsSort: [
            { columnKey: 'created_at', order: -1 } as ObservationsSorting | null,
            {
                setObservationsSort: (_, { sorting }) => sorting,
                restoreObservationsTableState: (_, { sort }) => sort,
            },
        ],
        observationsLoading: [
            false,
            {
                // Background polls reload silently so the table stays interactable; only foreground loads show the overlay.
                loadObservations: (state, { background }) => (background ? state : true),
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
            },
        ],
        observationStatsApi: [
            null as ObservationStatsApi | null,
            {
                loadObservationStatsSuccess: (_, { stats }) => stats,
            },
        ],
        observationStatsApiLoading: [
            false,
            {
                loadObservationStats: () => true,
                loadObservationStatsSuccess: () => false,
                loadObservationStatsFailure: () => false,
            },
        ],
        scannerEstimate: [
            null as EstimateResponseApi | null,
            {
                loadScannerEstimateSuccess: (_, { estimate }) => estimate,
                loadScannerEstimateFailure: () => null,
            },
        ],
        scannerEstimateError: [
            null as string | null,
            {
                requestScannerEstimate: () => null,
                loadScannerEstimateSuccess: () => null,
                loadScannerEstimateFailure: (_, { error }) => error,
            },
        ],
        scannerEstimateLoading: [
            false,
            {
                requestScannerEstimate: () => true,
                loadScannerEstimate: () => true,
                loadScannerEstimateSuccess: () => false,
                loadScannerEstimateFailure: () => false,
            },
        ],
        estimateRequestVersion: [
            0,
            {
                requestScannerEstimate: (state: number) => state + 1,
            },
        ],
        observationStatusFilter: [
            [] as ObservationStatusValue[],
            {
                setObservationStatusFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
                restoreObservationsTableState: (_, { status }) => status,
            },
        ],
        observationTriggeredByFilter: [
            [] as ObservationTriggeredByValue[],
            {
                setObservationTriggeredByFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
                restoreObservationsTableState: (_, { triggeredBy }) => triggeredBy,
            },
        ],
        observationVerdictFilter: [
            [] as ObservationVerdictValue[],
            {
                setObservationVerdictFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
                restoreObservationsTableState: (_, { verdict }) => verdict,
            },
        ],
        observationTagFilter: [
            [] as string[],
            {
                setObservationTagFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
                restoreObservationsTableState: (_, { tags }) => tags,
            },
        ],
        observationMinScoreFilter: [
            null as number | null,
            {
                setObservationScoreRange: (_, { minScore }) => minScore,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { minScore }) => minScore,
            },
        ],
        observationMaxScoreFilter: [
            null as number | null,
            {
                setObservationScoreRange: (_, { maxScore }) => maxScore,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { maxScore }) => maxScore,
            },
        ],
        observationSubjectFilter: [
            '' as string,
            {
                setObservationSubjectFilter: (_, { value }) => value,
                clearObservationFilters: () => '',
                restoreObservationsTableState: (_, { subject }) => subject,
            },
        ],
        observationDateFrom: [
            null as string | null,
            {
                setObservationDateRange: (_, { dateFrom }) => dateFrom,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { dateFrom }) => dateFrom,
            },
        ],
        observationDateTo: [
            null as string | null,
            {
                setObservationDateRange: (_, { dateTo }) => dateTo,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { dateTo }) => dateTo,
            },
        ],
        observationBackfillFilter: [
            null as string | null,
            {
                setObservationBackfillFilter: (_, { value }) => value,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { backfillId }) => backfillId,
            },
        ],
        observationVariantFilter: [
            null as string | null,
            {
                setObservationVariantFilter: (_, { value }) => value,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { variant }) => variant,
            },
        ],
        observationWatchGroupFilter: [
            null as string | null,
            {
                setObservationWatchGroupFilter: (_, { value }) => value,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { watchGroup }) => watchGroup,
            },
        ],
        // Narrows a similar-sessions list to the kinds the Highlights feed showed, so it matches the card's count.
        observationWatchCategoryFilter: [
            null as string | null,
            {
                setObservationWatchGroupFilter: () => null,
                clearObservationFilters: () => null,
                restoreObservationsTableState: (_, { watchCategory }) => watchCategory,
            },
        ],
        chartDateFrom: ['-14d' as string | null, { setChartDateRange: (_, { dateFrom }) => dateFrom }],
        chartDateTo: [null as string | null, { setChartDateRange: (_, { dateTo }) => dateTo }],
    }),

    selectors({
        isNew: [(_, p) => [p.id], (id: string) => id === 'new'],
        // A duration filter that can't overlap Vision's scannable window would scan nothing (e.g. active time
        // > 1h, which the ceiling always skips). Surfaced as a save-blocking reason rather than a form error,
        // since kea-forms can't attach a scalar error to the object-typed `query` field.
        durationValidationError: [
            (s) => [s.scanner],
            (scanner: ReplayScanner | null): string | null => {
                const durationFilter = scanner?.query
                    ? recordingsQueryToUniversalFilters(scanner.query).duration?.[0]
                    : undefined
                return durationFilter ? durationFilterError(clampDurationFilter(durationFilter)) : null
            },
        ],
        // Stepper badges show errors only after a failed submit; until then every step reads clean.
        stepErrors: [
            (s) => [s.showScannerErrors, s.scannerValidationErrors, s.durationValidationError],
            (
                showScannerErrors: boolean,
                scannerValidationErrors: DeepPartialMap<ScannerFormValues, ValidationErrorType>,
                durationValidationError: string | null
            ): Partial<Record<ScannerEditorStep, string[]>> =>
                showScannerErrors
                    ? scannerStepErrors({ ...scannerValidationErrors, duration: durationValidationError })
                    : {},
        ],
        linkedExperimentContext: [
            (s) => [s.experimentContext, s.experimentContextLinked],
            (
                experimentContext: ExperimentScannerContext | null,
                experimentContextLinked: boolean
            ): ExperimentScannerContext | null => (experimentContextLinked ? experimentContext : null),
        ],
        // Started from an experiment as an experiment scanner: the experiment fixes the type, so the
        // wizard offers no other type and no goal step.
        lockedToExperimentScanner: [
            (s) => [s.linkedExperimentContext, s.scanner],
            (linkedExperimentContext: ExperimentScannerContext | null, scanner: ScannerFormValues | null): boolean =>
                !!linkedExperimentContext && scanner?.scanner_type === 'experiment',
        ],
        hasUnsavedChanges: [
            (s) => [s.scanner, s.originalScanner],
            (scanner: ReplayScanner | null, original: ReplayScanner | null): boolean => {
                if (!scanner || !original) {
                    return false
                }
                return !objectsEqual(omitStamps(scanner), omitStamps(original))
            },
        ],
        hasObservationsInFlight: [
            (s) => [s.observationStatsApi],
            (stats: ObservationStatsApi | null): boolean => (stats?.status_counts.in_flight ?? 0) > 0,
        ],
        hasActiveObservationFilters: [
            (s) => [
                s.observationStatusFilter,
                s.observationTriggeredByFilter,
                s.observationVerdictFilter,
                s.observationTagFilter,
                s.observationMinScoreFilter,
                s.observationMaxScoreFilter,
                s.observationSubjectFilter,
                s.observationDateFrom,
                s.observationDateTo,
                s.observationBackfillFilter,
                s.observationVariantFilter,
                s.observationWatchGroupFilter,
            ],
            (
                statusFilter: ObservationStatusValue[],
                triggeredByFilter: ObservationTriggeredByValue[],
                verdictFilter: ObservationVerdictValue[],
                tagFilter: string[],
                minScore: number | null,
                maxScore: number | null,
                subjectFilter: string,
                dateFrom: string | null,
                dateTo: string | null,
                backfillFilter: string | null,
                variantFilter: string | null,
                watchGroupFilter: string | null
            ): boolean =>
                statusFilter.length > 0 ||
                triggeredByFilter.length > 0 ||
                verdictFilter.length > 0 ||
                tagFilter.length > 0 ||
                minScore !== null ||
                maxScore !== null ||
                subjectFilter.trim().length > 0 ||
                dateFrom !== null ||
                dateTo !== null ||
                backfillFilter !== null ||
                variantFilter !== null ||
                watchGroupFilter !== null,
        ],
        // Carried into observation detail links so server-computed prev/next neighbors honor the table's
        // filters + sort, and so the observation page can send the reader back to this exact view.
        observationDetailLinkParams: [
            (s) => [
                s.observationsPage,
                s.observationStatusFilter,
                s.observationTriggeredByFilter,
                s.observationVerdictFilter,
                s.observationTagFilter,
                s.observationMinScoreFilter,
                s.observationMaxScoreFilter,
                s.observationSubjectFilter,
                s.observationDateFrom,
                s.observationDateTo,
                s.observationBackfillFilter,
                s.observationVariantFilter,
                s.observationWatchGroupFilter,
                s.observationWatchCategoryFilter,
                s.observationsSort,
                s.scanner,
            ],
            (
                observationsPage: number,
                observationStatusFilter: ObservationStatusValue[],
                observationTriggeredByFilter: ObservationTriggeredByValue[],
                observationVerdictFilter: ObservationVerdictValue[],
                observationTagFilter: string[],
                observationMinScoreFilter: number | null,
                observationMaxScoreFilter: number | null,
                observationSubjectFilter: string,
                observationDateFrom: string | null,
                observationDateTo: string | null,
                observationBackfillFilter: string | null,
                observationVariantFilter: string | null,
                observationWatchGroupFilter: string | null,
                observationWatchCategoryFilter: string | null,
                observationsSort: ObservationsSorting | null,
                scanner: ReplayScanner | null
            ): Record<string, string | number> => {
                const listValues = {
                    observationStatusFilter,
                    observationTriggeredByFilter,
                    observationVerdictFilter,
                    observationTagFilter,
                    observationMinScoreFilter,
                    observationMaxScoreFilter,
                    observationSubjectFilter,
                    observationDateFrom,
                    observationDateTo,
                    observationBackfillFilter,
                    observationVariantFilter,
                    observationWatchGroupFilter,
                    observationWatchCategoryFilter,
                    observationsSort,
                    observationsPage,
                    scanner,
                }
                // The same filter + sort + page the list URL carries, so "back" restores this exact view.
                const params: Record<string, string | number> = {
                    ...observationListUrlParams(listValues),
                    tab: ReplayScannerTab.Observations,
                }
                // Prev/next reads `order_by` (an API key) to fetch neighbors in the table's order. It
                // rides alongside `sort` because the observation page can't map `sort` to `order_by`
                // itself: resolveOrderByKey needs the scanner type, unknown until the observation loads.
                const orderBy = buildObservationListParams(listValues).order_by
                if (orderBy) {
                    params.order_by = orderBy
                }
                return params
            },
        ],
        // Tag options for the observations-list Tag filter pill. Wrapped in an inline arrow with an
        // explicit return type so kea-typegen can infer it (it can't from bare function references).
        availableTags: [
            (s) => [s.observationStatsApi],
            (stats: ObservationStatsApi | null): string[] => availableTagsFromStats(stats),
        ],
        // The observations metric strip (Total / Succeeded / Failed / Ineligible / In flight).
        // The per-type overview panels (verdict mix, tag rankings, score distribution, coverage) moved
        // to the Overview tab (scannerOverviewLogic), which derives them from the same helpers.
        observationStats: [
            (s) => [s.observationStatsApi],
            (stats: ObservationStatsApi | null): ObservationStatusStats => deriveObservationStatusStats(stats),
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.scanner, s.isNew],
            (scanner: ReplayScanner | null, isNew: boolean): SidePanelSceneContext | null => {
                return scanner && !isNew
                    ? {
                          access_control_resource: 'replay_scanner',
                          access_control_resource_id: scanner.id,
                      }
                    : null
            },
        ],
        // The toggle lives in the UI-only `credit_limit_enabled` field; scanners straight from the API
        // derive it from having a limit set. Decoding it here keeps the form validator and the editor
        // card from drifting apart on what "on but empty" means.
        creditLimitState: [
            (s) => [s.scanner, s.scannerEstimate, s.scannerEstimateLoading, s.creditLimitUnit],
            (
                scanner: ScannerFormValues | null,
                estimate: EstimateResponseApi | null,
                estimateLoading: boolean,
                unit: CreditLimitUnit
            ): CreditLimitState => {
                const limit = typeof scanner?.credit_limit === 'number' ? scanner.credit_limit : null
                const estimatedMonthly = estimate?.estimated_credits_per_month ?? null
                // A reloading estimate still prices the previous model, so the model table stands in until it lands.
                const creditsPerObservation =
                    (estimateLoading ? undefined : estimate?.credits_per_observation) ??
                    (scanner ? OBSERVATION_CREDITS_BY_MODEL[scanner.model] : undefined) ??
                    null
                return {
                    limit,
                    unit: creditsPerObservation ? unit : 'credits',
                    observationLimit:
                        limit !== null && creditsPerObservation
                            ? creditsToObservations(limit, creditsPerObservation)
                            : null,
                    isOn: scanner?.credit_limit_enabled ?? limit !== null,
                    estimatedMonthly,
                    estimatedMonthlyObservations: estimate?.estimated_observations_per_month ?? null,
                    creditsPerObservation,
                    isBelowEstimate: limit !== null && estimatedMonthly !== null && limit < estimatedMonthly,
                    // A cap under one scan's cost never admits a single scan, so the scanner is stopped from
                    // the moment it is saved.
                    cannotAffordOneScan:
                        limit !== null && creditsPerObservation !== null && limit < creditsPerObservation,
                    // No estimate yet, or a zero one: null leaves the field empty rather than inventing a number.
                    seedValue:
                        estimatedMonthly !== null && estimatedMonthly > 0
                            ? // A seed under one scan's price would stop the scanner before its first scan.
                              Math.max(
                                  creditsPerObservation ?? 1,
                                  Math.round(estimatedMonthly * CREDIT_LIMIT_SEED_HEADROOM)
                              )
                            : null,
                }
            },
        ],
    }),

    listeners(({ actions, props, values, cache }) => {
        const reschedulePoll = (): void => {
            scheduleObservationPoll(
                cache.disposables,
                shouldPollObservations(values.hasObservationsInFlight, values.pollUntil),
                () => reloadObservationsAndStats(true)
            )
        }
        const reloadObservationsAndStats = (background = false): void => {
            if (values.observationsActive) {
                actions.loadObservations(background)
            }
            actions.loadObservationStats()
        }
        const persistDraft = (): void => {
            if (props.id !== 'new' || cache.restoringDraft) {
                return
            }
            const teamId = teamLogic.findMounted()?.values.currentTeamId
            if (!teamId || !values.scanner || !values.originalScanner) {
                return
            }
            if (objectsEqual(omitStamps(values.scanner), omitStamps(values.originalScanner))) {
                clearScannerDraft()
                actions.setScannerDraftSavedAt(null)
                return
            }
            const linkedExperimentId = values.linkedExperimentContext?.experiment.id
            const savedAt = writeScannerDraft(
                teamId,
                values.scanner,
                typeof linkedExperimentId === 'number' ? linkedExperimentId : null
            )
            if (savedAt === null) {
                // A failed write leaves any older draft behind; drop it so it can't resurrect stale edits.
                clearScannerDraft()
            }
            cache.draftTouched = savedAt !== null
            // Recorded here for the resume toast. By the time the scene unmounts the router already
            // points at wherever the user navigated, so the step has to be captured while editing.
            cache.lastEditedStep = scannerEditorSceneLogic.findMounted()?.values.step ?? cache.lastEditedStep
            actions.setScannerDraftSavedAt(savedAt)
        }
        return {
            loadObservationsSuccess: ({ observations, total }) => {
                lastObservationsPage.current = {
                    rows: observations,
                    number: values.observationsPage,
                    pageSize: OBSERVATIONS_PAGE_SIZE,
                    total,
                    filterParams: neighborFilterParams(values.observationDetailLinkParams),
                }
            },
            // kea-forms' exact rejection for failed client-side validation. API failures toast in submit's catch.
            submitScannerFailure: async ({ error }) => {
                if (error?.message !== 'Validation Failed') {
                    return
                }
                const editor = scannerEditorSceneLogic.findMounted()
                const currentStep = editor?.values.step
                const recordingsFirst = editor?.values.recordingsFirst ?? false
                const steps = scannerEditorSteps(recordingsFirst)
                const errors = { ...values.scannerValidationErrors, duration: values.durationValidationError }
                // Enter submits the whole form, so leaving a step whose own fields are clean must behave like
                // its Next button: move on, rather than red-flag fields the user has not reached yet.
                if (currentStep && advancesWithoutSubmit(currentStep, recordingsFirst, errors)) {
                    const next = nextScannerEditorStep(currentStep, steps)
                    if (next) {
                        router.actions.push(scannerStepUrlWithParams(next, props.id, router.values.searchParams))
                    }
                    return
                }
                const erroredStep = firstErroredScannerStep(errors, steps)
                if (erroredStep && erroredStep !== currentStep) {
                    router.actions.push(scannerStepUrlWithParams(erroredStep, props.id, router.values.searchParams))
                }
                // Yield so the step change renders before scrollToFormError looks for `.Field--error`.
                await Promise.resolve()
                scrollToFormError({
                    fallbackErrorMessage: 'Some scanner settings are invalid. Check each step for errors.',
                })
            },

            loadScanner: async () => {
                if (props.id === 'new') {
                    const teamId = teamLogic.findMounted()?.values.currentTeamId
                    const draft = teamId ? readScannerDraft(teamId) : null
                    const teamName = teamLogic.findMounted()?.values.currentTeam?.name
                    const experimentParams = parseExperimentScannerParams(router.values.searchParams)
                    const goalParam =
                        typeof router.values.searchParams.goal === 'string'
                            ? router.values.searchParams.goal.trim()
                            : ''
                    // Consumed unconditionally on every wizard entry: a cross-product hand-off must
                    // not stay armed for the rest of the tab session and prefill a later,
                    // unrelated wizard visit.
                    const handoff = consumeScannerHandoffIntent()
                    const armedGoal = consumeScannerGoalDraftIntent()
                    const entryPoint = scannerEntryPoint(
                        handoff?.source ?? armedGoal?.source ?? router.values.searchParams.entry_point
                    )
                    if (entryPoint) {
                        actions.setEntryPoint(entryPoint)
                    }
                    // Prefill precedence: a cross-product hand-off (a whole scanner, armed by an
                    // in-tab click moments before navigation), then an experiment deep link, then
                    // an explicit ?filters= query (both carry fully built state), then a saved
                    // draft, then the free-text goal. A URL carrying both ?filters= and ?goal=
                    // deterministically takes the filters and drops the goal.
                    const hasFiltersPrefill = 'filters' in router.values.searchParams
                    const prefillQuery = prefillQueryFromUrl()
                    // Strip the params the wizard has now consumed so a reload doesn't re-run the prefill
                    // over the user's edits: the experiment deep-link params, the goal param, and the
                    // `?filters=` prefill. One replace covers all of them and preserves the URL hash,
                    // which a second back-to-back replace would drop.
                    const nextParams = { ...router.values.searchParams }
                    if (experimentParams) {
                        delete nextParams.experiment
                        delete nextParams.variant
                    }
                    if (nextParams.goal !== undefined) {
                        delete nextParams.goal
                    }
                    if ('filters' in nextParams) {
                        delete nextParams.filters
                    }
                    if ('entry_point' in nextParams) {
                        delete nextParams.entry_point
                    }
                    if (Object.keys(nextParams).length !== Object.keys(router.values.searchParams).length) {
                        router.actions.replace(router.values.location.pathname, nextParams, router.values.hashParams)
                    }
                    if (handoff) {
                        posthog.capture('replay_vision_scanner_creation_started', {
                            creation_method: 'handoff',
                            template_key: null,
                            source: handoff.source,
                            entry_point: values.entryPoint,
                        })
                        // Same fresh-intent rule as the experiment deep link: the hand-off was
                        // armed by a click moments before navigation, so it outranks a saved
                        // draft; restoringDraft guards persistDraft so the prefill can't clobber
                        // that draft.
                        cache.restoringDraft = true
                        try {
                            actions.loadScannerSuccess(newScanner(teamName))
                            actions.setScannerValues(handoff.scanner)
                        } finally {
                            cache.restoringDraft = false
                        }
                        return
                    }
                    if (experimentParams) {
                        // The two deep links combine rather than compete: the replay filters entry
                        // point sends targeting and filters together, because exposure can't ride
                        // inside `query` and dropping either one silently rescopes the scanner.
                        // A blank start carries the monitor's default name, which reads wrong once the
                        // prefill turns it into an experiment scanner.
                        const experimentBase = {
                            ...newScanner(teamName),
                            ...(experimentScannersEnabled()
                                ? { name: defaultScannerName(teamName, 'experiment') }
                                : {}),
                            ...(prefillQuery ? { query: prefillQuery } : {}),
                        }
                        // An experiment deep link expresses fresh intent, so it outranks a saved
                        // draft; restoringDraft guards persistDraft so the prefill can't clobber the
                        // draft this user may already have for the next plain entry.
                        cache.restoringDraft = true
                        try {
                            const experiment = await api.experiments.get(experimentParams.experimentId)
                            const context: ExperimentScannerContext = {
                                experiment,
                                variantKey: reconcileVariantKey(experiment, experimentParams.variantKey),
                            }
                            const prefilled = prefillScannerForExperiment(
                                experimentBase,
                                context,
                                experimentScannersEnabled()
                            )
                            // Set the context only after the prefill is built, so a throw inside it
                            // doesn't leave a dangling context that the next startFromScratch re-applies.
                            actions.linkExperimentContext(context)
                            actions.loadScannerSuccess(prefilled)
                        } catch {
                            // Clear any context a partial run left set before surfacing the failure.
                            actions.setExperimentContext(null)
                            lemonToast.error("Couldn't load the experiment. Set recording filters manually instead.")
                            // Keep the filters that came with the link: they're the part of the
                            // hand-off that survived, and re-entering them by hand is the fallback.
                            actions.loadScannerSuccess(experimentBase)
                        } finally {
                            cache.restoringDraft = false
                        }
                        return
                    }
                    // A `?filters=` deep link expresses fresh intent (e.g. "save these playlist
                    // filters as a scanner"), so it seeds the query and outranks a saved draft;
                    // restoringDraft guards persistDraft so the prefill can't delete that draft.
                    if (prefillQuery) {
                        cache.restoringDraft = true
                        try {
                            actions.loadScannerSuccess({ ...newScanner(teamName), query: prefillQuery })
                        } finally {
                            cache.restoringDraft = false
                        }
                        return
                    }
                    cache.restoringDraft = true
                    try {
                        actions.loadScannerSuccess(newScanner(teamName))
                        if (draft) {
                            actions.setScannerValues(draft.scanner)
                            actions.setScannerDraftSavedAt(draft.savedAt)
                            // A draft made from an experiment prefill carries targeting the
                            // loadScannerSuccess above (a bare newScanner) didn't see. A draft started
                            // from an experiment link restores that link, so the wizard stays locked.
                            actions.rebuildExperimentContext(draft.linkedExperimentId)
                        }
                    } finally {
                        cache.restoringDraft = false
                    }
                    // The goal only prefills the AI box, so a crafted external ?goal= link can neither
                    // spend the user's AI allowance nor overwrite saved work without an explicit click.
                    if (goalParam && !hasFiltersPrefill) {
                        actions.setGoalDraftInput(goalParam)
                    }
                    const consented = !!organizationLogic.values.currentOrganization?.is_ai_data_processing_approved
                    if (armedGoal && !hasFiltersPrefill && consented && !values.goalDraftLoading) {
                        actions.setGoalDraftInput(armedGoal.goal)
                        if (armedGoal.query) {
                            actions.setGoalDraftQuery(armedGoal.query)
                        }
                        if (armedGoal.spend) {
                            // Mirrored into the goal page's controls, so a failed draft offers the same choice again.
                            actions.setGoalSpendMode('freeOnly' in armedGoal.spend ? 'free' : 'budget')
                            if ('monthlyCreditBudget' in armedGoal.spend) {
                                actions.setGoalBudgetInput(armedGoal.spend.monthlyCreditBudget)
                            }
                        }
                        const spend =
                            armedGoal.spend ??
                            goalSpendChoice(
                                values.goalSpendMode,
                                values.goalBudgetInput,
                                visionQuotaLogic.findMounted()?.values.freeCreditsLeft ?? null
                            ).spend
                        // With no budget to size it to, the goal stays in the box for the person to finish.
                        if (spend) {
                            actions.draftScannerFromGoal({
                                goal: armedGoal.goal,
                                spend,
                            })
                        }
                    }
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.loadScannerFailure() // Clear the loading flag — a bare return would spin forever.
                    return
                }
                try {
                    const response = await visionScannersRetrieve(String(teamId), props.id)
                    const scanner = scannerFromApi(response)
                    // The API never carries the UI-only toggle; materialize it so clearing a loaded limit
                    // still blocks the save instead of silently saving as unlimited.
                    actions.loadScannerSuccess({ ...scanner, credit_limit_enabled: scanner.credit_limit != null })
                } catch (error: any) {
                    lemonToast.error(`Failed to load scanner${error.detail ? `: ${error.detail}` : ''}`)
                    actions.loadScannerFailure()
                    router.actions.replace(urls.replayVision())
                }
            },

            loadScannerSuccess: ({ scanner }) => {
                actions.setScannerValues(scanner)
                // A `?sort=result` deep-link can't resolve order_by until the scanner type is known — refire now.
                if (
                    values.observationsActive &&
                    values.observationsSort?.columnKey === 'result' &&
                    scanner.scanner_type
                ) {
                    actions.loadObservations()
                    actions.loadObservationStats()
                }
                actions.rebuildExperimentContext()
            },

            // Rebuilds the experiment context from the form's current experiment — a loaded scanner
            // or a restored draft — so the editor can name it and list its variants wherever it came
            // from. The API hides the experiment from viewers denied it, so this never fetches an
            // experiment the viewer can't see. Fails soft: without the context the scanner still
            // edits normally.
            rebuildExperimentContext: async ({ linkedExperimentId }) => {
                const scope = scannerExperimentScope(values.scanner)
                if (!scope) {
                    // A card left over from earlier targeting would keep offering variants of an
                    // experiment this scanner no longer watches, and the picker would re-persist it.
                    if (values.experimentContext) {
                        actions.setExperimentContext(null)
                    }
                    return
                }
                if (values.experimentContext?.experiment.id === scope.experimentId) {
                    return
                }
                try {
                    const experiment = await api.experiments.get(scope.experimentId)
                    // The form's targeting can change while this request is in flight (starting from scratch or
                    // a draft discard resets it), so re-check before installing the card. Otherwise a late
                    // response restores a card for targeting the scanner no longer carries, which a later
                    // variant change would then re-persist.
                    const current = scannerExperimentScope(values.scanner)
                    if (
                        current?.experimentId !== scope.experimentId ||
                        values.experimentContext?.experiment.id === scope.experimentId
                    ) {
                        return
                    }
                    // The experiment type picks variants in its own config; only legacy targeting
                    // narrows to one variant through the card.
                    const variantKey =
                        values.scanner?.scanner_type === 'experiment' ? null : (current.variants?.[0] ?? null)
                    const context = { experiment, variantKey }
                    if (linkedExperimentId === scope.experimentId) {
                        actions.linkExperimentContext(context)
                    } else {
                        actions.setExperimentContext(context)
                    }
                } catch {
                    // The card simply doesn't render; targeting stays intact on the scanner.
                }
            },

            // The variants belong to the old experiment, so they reset with it. Only an unsaved scanner
            // gets here: the API fixes the experiment after creation.
            // Legacy targeting only. The reducer has already stored the new key; targeting lives in its
            // own field, so a variant change never touches `query` and filters added by hand survive.
            setExperimentVariant: () => {
                const context = values.experimentContext
                if (!context) {
                    return
                }
                actions.setScannerValue('experiment_targeting', buildExperimentTargeting(context))
            },

            setScannerExperiment: ({ experimentId }) => {
                // A failed rebuild would otherwise leave the previous experiment's context in place.
                if (values.experimentContext && values.experimentContext.experiment.id !== experimentId) {
                    actions.setExperimentContext(null)
                }
                actions.setScannerValues({ scanner_config: { experiment_id: experimentId, variants: null } })
                actions.rebuildExperimentContext()
            },

            // Clearing the context alone would leave the persisted targeting silently filtering to
            // exposed persons with nothing in the Triggers UI able to show or remove it.
            detachExperimentContext: () => {
                if (values.scanner?.experiment_targeting) {
                    actions.setScannerValue('experiment_targeting', null)
                }
            },

            // Changing type keeps the rest of the form: it spreads `current`, so an experiment
            // prefill's name and query carry over untouched. Only the config is reset for the new type.
            setScannerType: ({ scannerType }) => {
                const current = values.scanner
                if (!current) {
                    return
                }
                const teamName = teamLogic.values.currentTeam?.name
                // Only re-derive a name the user never edited, so a typed name always survives a type change.
                const keepsDefaultName =
                    !current.name?.trim() || current.name === defaultScannerName(teamName, current.scanner_type)
                const context = values.experimentContext
                // A wizard entered from an experiment keeps watching it when the type returns to experiment.
                const config =
                    scannerType === 'experiment' && context
                        ? experimentScannerConfig(context.experiment, context.variantKey ? [context.variantKey] : null)
                        : defaultConfigForType(scannerType)
                actions.resetScanner({
                    ...current,
                    name: keepsDefaultName ? defaultScannerName(teamName, scannerType) : current.name,
                    scanner_type: scannerType,
                    scanner_config: config,
                } as ScannerFormValues)
                persistDraft()
            },

            // Fires on request rather than result, so failed drafts still count as entering the AI path.
            draftScannerFromGoal: ({ request: { goal, templateKey, spend } }) => {
                posthog.capture('replay_vision_scanner_creation_started', {
                    creation_method: 'ai',
                    // Set when a starter wrote the goal and it was sent unedited, or when an experiment was picked,
                    // so the funnel can split typed goals from starter ones.
                    template_key: templateKey ?? null,
                    entry_point: values.entryPoint,
                    query_pinned: !!values.goalDraftQuery,
                    spend_mode: 'freeOnly' in spend ? 'free' : 'budget',
                    // The goal is customer text, so only its length is captured.
                    goal_length: goal.trim().length,
                })
                // Land on the overview immediately, in its skeleton state, so the wait reads as
                // progress rather than a stuck button.
                router.actions.push(urls.replayVisionScannerOverview('new'))
            },

            // A successful AI draft seeds the wizard form, which the overview then shows for review.
            draftScannerFromGoalSuccess: ({ goalDraft, payload }) => {
                if (!goalDraft) {
                    return
                }
                // The model call can take a while; if the user navigated away from the overview
                // skeleton meanwhile, their newer state wins and the stale draft is dropped.
                if (!router.values.location.pathname.endsWith(urls.replayVisionScannerOverview('new'))) {
                    return
                }
                // An experiment prefill (experiment type, scoped name, test-account setting) has to
                // survive the AI draft the same way it survives a fresh start, or a scanner started
                // from an experiment would end up watching every visitor instead of the participants.
                // A draft that named an experiment itself is fresher intent, so it wins.
                const asExperimentScanner = experimentScannersEnabled()
                const draftedExperiment = draftExperimentScope(goalDraft)
                const linkedContext = values.linkedExperimentContext
                const context = draftedExperiment ? null : linkedContext
                if (values.experimentContext && (draftedExperiment || !linkedContext)) {
                    // rebuildExperimentContext keeps a card whose experiment id already matches, so a
                    // draft that renames the variant would leave the Recordings step showing the old
                    // one while the scanner saves the new one. Drop the card and let it rebuild.
                    actions.setExperimentContext(null)
                }
                const freeOnlyDraft = !!goalDraft.free_only
                const base = newScanner(teamLogic.values.currentTeam?.name)
                actions.resetScanner(context ? prefillScannerForExperiment(base, context, asExperimentScanner) : base)
                const draftQuery = goalDraft.query as RecordingsQuery | undefined
                // Applied as form values (not baked into the reset) so the draft persists like hand-edited
                // input and survives a reload of the configure step.
                actions.setScannerValues({
                    // Saved with the scanner, so it keeps the intent it was drafted from.
                    goal: payload?.request.goal.trim() || null,
                    name: context ? experimentScannerName(goalDraft.name, context.experiment.name) : goalDraft.name,
                    description: goalDraft.description,
                    ...(asExperimentScanner
                        ? draftScannerTypeAndConfig(goalDraft, draftedExperiment, context)
                        : legacyDraftTypeAndConfig(goalDraft)),
                    // The drafted session filter (when the goal mapped to real screens or events); the
                    // triggers step shows it for review like any hand-picked filter. Under an
                    // experiment prefill it keeps that experiment's test-account setting.
                    ...(draftQuery
                        ? {
                              query: context
                                  ? { ...draftQuery, ...experimentScannerQuery(context.experiment) }
                                  : draftQuery,
                          }
                        : {}),
                    // The budget dials the draft solved; a draft whose costing failed keeps the wizard defaults.
                    ...(goalDraft.sampling_mode ? { sampling_mode: goalDraft.sampling_mode as SamplingMode } : {}),
                    ...(goalDraft.sampling_rate != null ? { sampling_rate: goalDraft.sampling_rate } : {}),
                    // The model the draft chose for the goal, and the credit cap set to the stated
                    // budget. credit_limit_enabled is UI-only form state, so turn it on alongside.
                    ...(goalDraft.model ? { model: goalDraft.model } : {}),
                    ...(freeOnlyDraft
                        ? { free_only: true, credit_limit: null, credit_limit_enabled: false }
                        : goalDraft.credit_limit != null
                          ? { credit_limit: goalDraft.credit_limit, credit_limit_enabled: true }
                          : {}),
                    // The experiment type carries the experiment. Without it, the experiment the goal
                    // named (or the one the wizard was entered from) stays legacy targeting.
                    experiment_targeting: asExperimentScanner
                        ? null
                        : draftedExperiment
                          ? {
                                experiment_id: draftedExperiment.experimentId,
                                variant: draftedExperiment.variants?.[0] ?? null,
                            }
                          : context
                            ? buildExperimentTargeting(context)
                            : null,
                })
                // Loads the experiment so the editor shows its name and variants, the same way it
                // does for a scanner started from the experiment itself.
                actions.rebuildExperimentContext()
                // The form now carries the drafted filter, so count what it will actually watch.
                actions.loadScannerEstimate()
            },

            draftScannerFromGoalFailure: ({ errorObject }) => {
                lemonToast.error(errorObject?.detail ?? "Couldn't draft a scanner. Try again in a moment.")
                // The draft moved to the overview skeleton on request; with no draft to show,
                // send the user back to the questions, dropping the empty overview from history when it was pushed.
                if (router.values.location.pathname.endsWith(urls.replayVisionScannerOverview('new'))) {
                    if (router.values.lastMethod === 'PUSH') {
                        window.history.back()
                    } else {
                        router.actions.replace(urls.replayVisionScannerGoal('new'))
                    }
                }
            },

            clearClassifierTags: () => {
                const scanner = values.scanner
                if (!scanner || scanner.scanner_type !== 'classifier') {
                    return
                }
                if ((scanner.scanner_config.tags ?? []).length > 0) {
                    actions.setScannerValue(['scanner_config', 'tags'], [])
                }
            },

            // kea-forms fires setScannerValue(s) per field change — debounced so drags don't fire a request per tick.
            setScannerValue: () => {
                actions.requestScannerEstimate()
                persistDraft()
            },
            setScannerValues: () => {
                actions.requestScannerEstimate()
                persistDraft()
            },
            startFromScratch: () => {
                // Counterpart of the AI capture, so the creation funnel can split by path.
                posthog.capture('replay_vision_scanner_creation_started', {
                    creation_method: 'scratch',
                    template_key: null,
                    entry_point: values.entryPoint,
                })
                clearScannerDraft()
                actions.setScannerDraftSavedAt(null)
                // An experiment prefill (targeted query, scoped name) has to survive the reset, so
                // re-apply it when the wizard was entered from an experiment.
                const base = newScanner(teamLogic.values.currentTeam?.name)
                const context = values.linkedExperimentContext
                if (values.experimentContext && !context) {
                    actions.setExperimentContext(null)
                }
                actions.resetScanner(
                    context ? prefillScannerForExperiment(base, context, experimentScannersEnabled()) : base
                )
            },
            discardScannerDraft: () => {
                // Storage holds one draft, and it belongs to the new-scanner wizard.
                if (props.id === 'new') {
                    clearScannerDraft()
                    actions.setScannerDraftSavedAt(null)
                }
                // Discarding ends the experiment flow; a scanner started next must not inherit it.
                actions.setExperimentContext(null)
                actions.resetScanner(values.originalScanner ?? newScanner())
            },
            scannerSaved: () => {
                actions.requestScannerEstimate()
                // Saving recomputes the persisted estimate, which shifts the org-wide fleet sum.
                refreshVisionQuota()
                if (props.id === 'new') {
                    clearScannerDraft()
                    actions.setScannerDraftSavedAt(null)
                    // The saved scanner's experiment association ends here; a new scanner started in
                    // the same session must not re-apply this experiment's query and name.
                    actions.setExperimentContext(null)
                }
            },

            requestScannerEstimate: () => {
                cache.disposables.add(() => {
                    const id = setTimeout(() => actions.loadScannerEstimate(), 300)
                    return () => clearTimeout(id)
                }, 'scannerEstimateDebounce')
            },

            loadScannerEstimate: async (_, breakpoint) => {
                const teamId = teamLogic.values.currentTeamId
                const scanner = values.scanner
                if (!teamId || !scanner) {
                    actions.loadScannerEstimateFailure()
                    return
                }
                const version = values.estimateRequestVersion
                try {
                    const scope = scannerExperimentScope(scanner)
                    const isExperimentType = scanner.scanner_type === 'experiment'
                    const context = values.experimentContext
                    const waitsForLaunch =
                        context?.experiment.id === scope?.experimentId && !context?.experiment.start_date
                    if (isExperimentType && (!scope || waitsForLaunch)) {
                        // No population to count yet: without an experiment the preview would count
                        // every session, and a draft has no exposed sessions.
                        actions.loadScannerEstimateFailure(null)
                        return
                    }
                    const response = await visionScannersEstimateCreate(String(teamId), {
                        query: scanner.query ?? undefined,
                        // Sent alongside the query so the preview counts the same exposed-person
                        // population the scan will, instead of every eligible session. The API
                        // refuses a request that sends both fields.
                        experiment_targeting: isExperimentType ? null : (scanner.experiment_targeting ?? null),
                        experiment:
                            isExperimentType && scope
                                ? { experiment_id: scope.experimentId, variants: scope.variants }
                                : null,
                        sampling_rate: scanner.sampling_rate,
                        // The proposed model prices the credit estimate.
                        model: scanner.model,
                        sampling_mode: scanner.sampling_mode,
                        // Exclude the edited scanner from the others-sum so the forecast doesn't double-count it.
                        scanner_id: props.id !== 'new' ? props.id : null,
                    })
                    breakpoint()
                    if (values.estimateRequestVersion !== version) {
                        return
                    }
                    actions.loadScannerEstimateSuccess(response)
                } catch (error: any) {
                    if (error instanceof Error && isBreakpoint(error)) {
                        throw error
                    }
                    // eslint-disable-next-line no-console
                    console.warn('[replay-vision] scanner estimate failed', error)
                    if (values.estimateRequestVersion !== version) {
                        return
                    }
                    const detail = typeof error?.detail === 'string' ? error.detail : null
                    const message = typeof error?.message === 'string' ? error.message : null
                    actions.loadScannerEstimateFailure(detail ?? message)
                }
            },

            toggleEnabled: async () => {
                const scanner = values.scanner
                if (props.id === 'new' || !scanner) {
                    actions.toggleEnabledFailure()
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.toggleEnabledFailure()
                    return
                }
                const next = !scanner.enabled
                actions.setScannerValue('enabled', next)
                try {
                    await visionScannersPartialUpdate(String(teamId), props.id, { enabled: next })
                    actions.toggleEnabledSuccess(next)
                    refreshVisionQuota()
                    lemonToast.success(`Scanner ${next ? 'enabled' : 'disabled'}`)
                } catch (error: any) {
                    actions.setScannerValue('enabled', !next)
                    const verb = next ? 'enable' : 'disable'
                    lemonToast.error(`Failed to ${verb} scanner${error.detail ? `: ${error.detail}` : ''}`)
                    actions.toggleEnabledFailure()
                }
            },

            turnOffFreeOnly: async () => {
                const teamId = teamLogic.values.currentTeamId
                if (props.id === 'new' || !values.scanner || !teamId) {
                    actions.turnOffFreeOnlyFailure()
                    return
                }
                try {
                    const saved = await visionScannersPartialUpdate(String(teamId), props.id, { free_only: false })
                    actions.setScannerValues(freeOnlyFields(saved))
                    actions.turnOffFreeOnlySuccess(saved)
                    refreshVisionQuota()
                    lemonToast.success('Free credits only turned off')
                } catch (error: any) {
                    lemonToast.error(`Couldn't turn off free credits only${error.detail ? `: ${error.detail}` : ''}`)
                    actions.turnOffFreeOnlyFailure()
                }
            },

            turnOnSelfDriving: async () => {
                const teamId = teamLogic.values.currentTeamId
                if (props.id === 'new' || !values.scanner || !teamId) {
                    actions.turnOnSelfDrivingFailure()
                    return
                }
                try {
                    const response = await visionScannersPartialUpdate(String(teamId), props.id, {
                        emits_signals: true,
                    })
                    actions.setScannerValue('emits_signals', true)
                    actions.setScannerValue('scanner_version', response.scanner_version)
                    actions.setScannerValue('updated_at', response.updated_at)
                    actions.turnOnSelfDrivingSuccess(response.scanner_version, response.updated_at)
                    lemonToast.success('Self-driving turned on')
                } catch (error: any) {
                    lemonToast.error(`Failed to turn on self-driving${error.detail ? `: ${error.detail}` : ''}`)
                    actions.turnOnSelfDrivingFailure()
                }
            },

            triggerOnDemandObservation: async ({ sessionId, silent }) => {
                if (props.id === 'new') {
                    actions.triggerOnDemandObservationFailure()
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.triggerOnDemandObservationFailure()
                    return
                }
                const trimmed = sessionId.trim()
                if (!trimmed) {
                    actions.triggerOnDemandObservationFailure()
                    return
                }
                try {
                    await visionScannersObserveCreate(String(teamId), props.id, { session_id: trimmed })
                    if (!silent) {
                        lemonToast.success(
                            'Scanning recording — the observation will appear on the Observations tab shortly.'
                        )
                    }
                    actions.triggerOnDemandObservationSuccess()
                    actions.refreshObservations()
                } catch (error: any) {
                    lemonToast.error(`Failed to scan session${error.detail ? `: ${error.detail}` : ''}`)
                    actions.triggerOnDemandObservationFailure()
                }
            },

            triggerOnDemandObservationSuccess: () => refreshVisionQuota(),

            retryObservation: async ({ observationId }) => {
                if (props.id === 'new' || !(await requestObservationRetry(observationId))) {
                    actions.retryObservationFailure(observationId)
                    return
                }
                actions.retryObservationSuccess(observationId)
                reloadObservationsAndStats()
            },

            refreshObservations: () => reloadObservationsAndStats(),

            copyAllObservations: async (_, breakpoint) => {
                try {
                    const teamId = teamLogic.values.currentTeamId
                    if (props.id === 'new' || !teamId) {
                        return
                    }
                    // Only succeeded rows have a result body to paste.
                    const params = {
                        ...buildObservationListParams(values, COPY_ALL_OBSERVATIONS_LIMIT, 0),
                        status: 'succeeded',
                    }
                    const response = await visionScannersObservationsList(String(teamId), props.id, params)
                    breakpoint()
                    const results = (response.results ?? []) as ReplayObservationApi[]
                    const texts = results.map(observationClipboardText).filter((text): text is string => text !== null)
                    if (texts.length === 0) {
                        lemonToast.info('No results to copy for the current filters.')
                        return
                    }
                    const count = response.count ?? texts.length
                    const description =
                        count > results.length
                            ? `the latest ${texts.length.toLocaleString()} of ${count.toLocaleString()} results`
                            : `${texts.length.toLocaleString()} result${texts.length === 1 ? '' : 's'}`
                    await copyToClipboard(texts.join('\n\n---\n\n'), description)
                } finally {
                    actions.copyAllObservationsFinished()
                }
            },

            setObservationsActive: ({ active }) => {
                if (active) {
                    actions.loadObservations()
                }
            },

            loadObservations: async (_, breakpoint) => {
                if (props.id === 'new') {
                    actions.loadObservationsSuccess([], 0)
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.loadObservationsFailure()
                    return
                }
                try {
                    const offset = (values.observationsPage - 1) * OBSERVATIONS_PAGE_SIZE
                    const params = buildObservationListParams(values, OBSERVATIONS_PAGE_SIZE, offset)
                    const response = await visionScannersObservationsList(String(teamId), props.id, params)
                    // Drop out-of-order responses — a newer load (filter change, poll, pagination) owns the table.
                    breakpoint()
                    const results = response.results ?? []
                    const count = response.count ?? 0
                    // A shrunken set (narrowed filter, concurrent change) can strand an out-of-range page.
                    if (results.length === 0 && count > 0 && values.observationsPage > 1) {
                        actions.setObservationsPage(Math.ceil(count / OBSERVATIONS_PAGE_SIZE))
                        return
                    }
                    actions.loadObservationsSuccess(results, count)
                } catch (error) {
                    if (error instanceof Error && isBreakpoint(error)) {
                        throw error
                    }
                    actions.loadObservationsFailure()
                }
            },

            setObservationsPage: () => actions.loadObservations(),
            restoreObservationsTableState: () => reloadObservationsAndStats(),
            setObservationsSort: () => actions.loadObservations(),
            // Any change to the filter set has to refresh both the current page and the aggregate cards above it.
            setObservationStatusFilter: () => reloadObservationsAndStats(),
            setObservationTriggeredByFilter: () => reloadObservationsAndStats(),
            setObservationVerdictFilter: () => reloadObservationsAndStats(),
            setObservationTagFilter: () => reloadObservationsAndStats(),
            setObservationScoreRange: async (_, breakpoint) => {
                // Typed into number inputs; debounce so each keystroke of "10" does not fire its own request.
                await breakpoint(300)
                reloadObservationsAndStats()
            },
            setObservationBackfillFilter: () => reloadObservationsAndStats(),
            setObservationVariantFilter: () => reloadObservationsAndStats(),
            setObservationWatchGroupFilter: () => reloadObservationsAndStats(),
            setObservationDateRange: () => reloadObservationsAndStats(),
            setObservationSubjectFilter: async (_, breakpoint) => {
                // Free-text search — debounce so typing doesn't fire a request per keystroke.
                await breakpoint(300)
                reloadObservationsAndStats()
            },
            clearObservationFilters: () => reloadObservationsAndStats(),

            setChartDateRange: () => {
                actions.loadObservationStats()
            },

            loadObservationStats: async (_, breakpoint) => {
                if (props.id === 'new') {
                    actions.loadObservationStatsFailure()
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    actions.loadObservationStatsFailure()
                    return
                }
                try {
                    // Stats endpoint accepts the same filters as the list, but `order_by` is meaningless on an aggregate.
                    const { order_by: _ignored, ...params } = buildObservationListParams(values)
                    const recentDays = daysFromDateRange(values.chartDateFrom, values.chartDateTo)
                    const response = await visionScannersObservationsStatsRetrieve(String(teamId), props.id, {
                        ...params,
                        recent_days: recentDays,
                    })
                    // Drop out-of-order responses; the superseding load reschedules the poll itself.
                    breakpoint()
                    actions.loadObservationStatsSuccess(response)
                } catch (error) {
                    if (error instanceof Error && isBreakpoint(error)) {
                        throw error
                    }
                    actions.loadObservationStatsFailure()
                }
            },

            // Rescheduled on failure too — a transient API hiccup shouldn't permanently kill the polling cycle.
            loadObservationStatsSuccess: reschedulePoll,
            loadObservationStatsFailure: reschedulePoll,
        }
    }),

    actionToUrl(({ values }) => {
        const buildSearchParams = (): Record<string, string | number | undefined> => {
            const next = { ...router.values.searchParams } as Record<string, string | number | undefined>
            // Clear the table's keys, then re-add only the ones the current state sets, so a cleared
            // filter or a return to page 1 drops its param rather than lingering.
            for (const key of OBSERVATION_LIST_URL_PARAM_KEYS) {
                delete next[key]
            }
            Object.assign(next, observationListUrlParams(values))
            return next
        }
        const writeUrl = (): [string, Record<string, string | number | undefined>] => [
            router.values.location.pathname,
            buildSearchParams(),
        ]
        // Replace (not push) so typing in the subject search doesn't spam browser history.
        const writeUrlReplace = (): [
            string,
            Record<string, string | number | undefined>,
            Record<string, string>,
            { replace: boolean },
        ] => [router.values.location.pathname, buildSearchParams(), {}, { replace: true }]
        return {
            setObservationsPage: writeUrl,
            setObservationsSort: writeUrl,
            setObservationStatusFilter: writeUrl,
            setObservationTriggeredByFilter: writeUrl,
            setObservationVerdictFilter: writeUrl,
            setObservationTagFilter: writeUrl,
            setObservationScoreRange: writeUrlReplace,
            setObservationDateRange: writeUrl,
            setObservationBackfillFilter: writeUrl,
            setObservationVariantFilter: writeUrl,
            setObservationWatchGroupFilter: writeUrl,
            setObservationSubjectFilter: writeUrlReplace,
            clearObservationFilters: writeUrl,
        }
    }),

    urlToAction(({ actions, values, props }) => ({
        // Restore as one atomic action (individual setters would reset the page); dispatch only on actual change.
        // A static pattern: url-pattern throws on an id with pattern tokens, e.g. a `)` copied from a Markdown link.
        [urls.replayVision(':id')]: ({ id }, searchParams) => {
            if (id !== props.id) {
                return
            }
            const pageRaw = Number(searchParams.page ?? 1)
            const page = Number.isFinite(pageRaw) ? Math.max(1, pageRaw) : 1
            const sort = parseSortParam(searchParams.sort) ?? DEFAULT_OBSERVATIONS_SORT
            const status = parseCsvParam<ObservationStatusValue>(searchParams.status, OBSERVATION_STATUS_VALUES)
            const triggeredBy = parseCsvParam<ObservationTriggeredByValue>(
                searchParams.triggered_by,
                OBSERVATION_TRIGGERED_BY_VALUES
            )
            const verdict = parseCsvParam<ObservationVerdictValue>(searchParams.verdict, OBSERVATION_VERDICT_VALUES)
            const tags = parseCsvParam<string>(searchParams.tags)
            const minScore = parseNumericParam(searchParams.min_score)
            const maxScore = parseNumericParam(searchParams.max_score)
            const subjectRaw = searchParams.recording_subject
            // String() so a numeric-looking subject (`?recording_subject=12345`) survives the router's coercion.
            const subject =
                typeof subjectRaw === 'string' ? subjectRaw : typeof subjectRaw === 'number' ? String(subjectRaw) : ''
            const dateFrom = typeof searchParams.date_from === 'string' ? searchParams.date_from : null
            const dateTo = typeof searchParams.date_to === 'string' ? searchParams.date_to : null
            const backfillId = typeof searchParams.backfill_id === 'string' ? searchParams.backfill_id : null
            // The new-scanner wizard reads its own `?variant=` for an experiment deep link; this list
            // filter only runs on a saved scanner's page. String() so a numeric key survives the router.
            const variantRaw = searchParams.variant
            const variant =
                typeof variantRaw === 'string' || typeof variantRaw === 'number' ? String(variantRaw) || null : null
            const watchGroup = typeof searchParams.watch_group === 'string' ? searchParams.watch_group : null
            const watchCategory =
                watchGroup && typeof searchParams.watch_category === 'string' ? searchParams.watch_category : null
            const sameAsCurrent =
                page === values.observationsPage &&
                sort.columnKey === values.observationsSort?.columnKey &&
                sort.order === values.observationsSort?.order &&
                objectsEqual(status, values.observationStatusFilter) &&
                objectsEqual(triggeredBy, values.observationTriggeredByFilter) &&
                objectsEqual(verdict, values.observationVerdictFilter) &&
                objectsEqual(tags, values.observationTagFilter) &&
                minScore === values.observationMinScoreFilter &&
                maxScore === values.observationMaxScoreFilter &&
                subject === values.observationSubjectFilter &&
                dateFrom === values.observationDateFrom &&
                dateTo === values.observationDateTo &&
                backfillId === values.observationBackfillFilter &&
                variant === values.observationVariantFilter &&
                watchGroup === values.observationWatchGroupFilter &&
                watchCategory === values.observationWatchCategoryFilter
            if (!sameAsCurrent) {
                actions.restoreObservationsTableState({
                    page,
                    sort,
                    status,
                    triggeredBy,
                    verdict,
                    tags,
                    minScore,
                    maxScore,
                    subject,
                    dateFrom,
                    dateTo,
                    backfillId,
                    variant,
                    watchGroup,
                    watchCategory,
                })
            }
        },
    })),

    beforeUnload(({ values, actions, props }) => ({
        enabled: (newLocation?: CombinedLocation) =>
            shouldGuardScannerNavigation({
                hasUnsavedChanges: values.hasUnsavedChanges,
                isSubmitting: values.isScannerSubmitting,
                hasSavedDraft: values.scannerDraftSavedAt !== null,
                scannerId: props.id,
                currentPathname: router.values.location.pathname,
                nextPathname: newLocation?.pathname,
                browserPathname: window.location.pathname,
            }),
        message: 'Leave scanner editor?\nChanges you made will be discarded.',
        onConfirm: () => {
            if (values.originalScanner) {
                actions.resetScanner(values.originalScanner)
            }
        },
    })),

    afterMount(({ actions, props, cache }) => {
        cache.draftTouched = false
        actions.loadScanner()
        if (props.id !== 'new') {
            actions.loadObservationStats()
        }
        // Setup re-runs when the tab becomes visible
        cache.disposables.add(() => {
            if (cache.teamRefreshArmed && !teamLogic.values.currentTeamLoading) {
                teamLogic.actions.refreshCurrentTeam()
            }
            cache.teamRefreshArmed = true
            return () => {}
        }, 'refreshTeamOnVisible')
    }),

    beforeUnmount(({ values, props, cache }) => {
        if (props.id === 'new' && cache.draftTouched && values.scannerDraftSavedAt !== null) {
            // Back to the step the last edit was on, not always the first one — returning to details
            // after editing recordings or budget reads as having lost those steps, even though the
            // values were restored. The goal step holds no edits, so it falls through to details.
            const step = cache.lastEditedStep
            const resumeUrl = scannerStepUrl(step && step !== 'goal' ? step : 'details', 'new')
            lemonToast.info('Draft saved', {
                button: {
                    label: 'Resume',
                    action: () => router.actions.push(resumeUrl),
                    dataAttr: 'vision-draft-resume-toast',
                },
            })
        }
    }),
])

export function leaveScannerEditor(scannerId: string, destination: string): void {
    // A save can finish after the user has left this scanner's editor, and must not pull them away from where they are.
    if (!scannerEditorPaths(scannerId).includes(removeProjectIdIfPresent(router.values.location.pathname))) {
        return
    }
    const editor = scannerEditorSceneLogic.findMounted()
    if (editor) {
        editor.actions.leaveEditor(destination)
    } else {
        router.actions.replace(destination)
    }
}

/** The step URLs of a scanner's editor wizard. */
function scannerEditorPaths(scannerId: string): string[] {
    return [
        ...scannerEditorSteps(false).map((step) => scannerStepUrl(step, scannerId)),
        // The goal flow's overview step is editor territory too, though it sits outside the manual stepper.
        scannerStepUrl('overview', scannerId),
    ]
}

/**
 * Whether leaving the current location should warn about losing unsaved scanner edits.
 * Only guards while actually inside this scanner's editor, and stays quiet for the
 * navigation the editor triggers itself: moving between its own steps, and the
 * programmatic redirect that a save/advance fires while submitting.
 */
export function shouldGuardScannerNavigation(params: {
    hasUnsavedChanges: boolean
    isSubmitting: boolean
    hasSavedDraft: boolean
    scannerId: string
    currentPathname: string
    nextPathname?: string
    browserPathname?: string
}): boolean {
    const { hasUnsavedChanges, isSubmitting, hasSavedDraft, scannerId, currentPathname, browserPathname } = params
    if (!hasUnsavedChanges || isSubmitting || hasSavedDraft) {
        return false
    }
    // kea-router passes no destination on browser back/forward, but by then the window already shows it.
    const nextPathname =
        params.nextPathname ??
        (browserPathname && removeProjectIdIfPresent(browserPathname) !== removeProjectIdIfPresent(currentPathname)
            ? browserPathname
            : undefined)
    // The router's stored pathname carries the `/project/:id` prefix, while `urls.*` never do,
    // so both sides must be normalized before comparing or the guard never engages.
    const editorPaths = scannerEditorPaths(scannerId)
    if (!editorPaths.includes(removeProjectIdIfPresent(currentPathname))) {
        return false
    }
    if (nextPathname && editorPaths.includes(removeProjectIdIfPresent(nextPathname))) {
        return false
    }
    return true
}
