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
import { scrollToFormError } from 'lib/forms/scrollToFormError'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { objectsEqual } from 'lib/utils/objects'
import { recordingsQueryToUniversalFilters } from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import type { RecordingsQuery } from '~/queries/schema/schema-general'

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
    visionScannersSuggestTagsCreate,
} from '../generated/api'
import { ObservationStatusEnumApi, ObservationTriggerEnumApi } from '../generated/api.schemas'
import type {
    DraftScannerResponseApi,
    EstimateResponseApi,
    ObservationStatsApi,
    ReplayObservationApi,
    TagSuggestionApi,
} from '../generated/api.schemas'
import type { ScannerTypeEnumApi } from '../generated/api.schemas'
import { OBSERVE_POLL_GRACE_MS, scheduleObservationPoll, shouldPollObservations } from '../logics/observationPolling'
import { requestObservationRetry } from '../logics/observationRetry'
import { refreshVisionQuota } from '../logics/visionQuotaLogic'
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
    parseExperimentScannerParams,
    prefillScannerForExperiment,
    reconcileVariantKey,
} from './experimentTargeting'
import { consumeGoalDraftIntent } from './goalDraftIntent'
import { clearScannerDraft, readScannerDraft, writeScannerDraft } from './scannerDraft'
import {
    SCANNER_EDITOR_STEPS,
    firstErroredScannerStep,
    scannerEditorSceneLogic,
    scannerStepUrl,
    scannerStepUrlWithParams,
    UNVALIDATED_SCANNER_STEPS,
} from './scannerEditorSceneLogic'
import type { ObservationStatusStats } from './scannerStats'
import { availableTagsFromStats, daysFromDateRange, deriveObservationStatusStats } from './scannerStats'
import { findScannerTemplate, newScanner } from './scannerTemplates'
import {
    MAX_CREDIT_LIMIT,
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
// Past this many rows the clipboard is the wrong tool.
const COPY_ALL_OBSERVATIONS_LIMIT = 500

function currentTemplateKey(): string | null {
    const value = router.values.searchParams.template
    return typeof value === 'string' ? value : null
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
    return { prompt: '' }
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

export interface CreditLimitState {
    /** The limit in credits, or null when the field is empty or the limit is off. */
    limit: number | null
    isOn: boolean
    estimatedMonthly: number | null
    creditsPerObservation: number | null
    isBelowEstimate: boolean
    cannotAffordOneScan: boolean
    /** What to put in the field when the user switches the limit on; null leaves it empty. */
    seedValue: number | null
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
    creditLimitState: CreditLimitState
    durationValidationError: string | null
    estimateRequestVersion: number
    experimentContext: ExperimentScannerContext | null
    goalBudgetInput: number | null
    goalDraft: DraftScannerResponseApi | null
    goalDraftInput: string
    goalDraftLoading: boolean
    hasActiveObservationFilters: boolean
    hasObservationsInFlight: boolean
    hasUnsavedChanges: boolean
    isNew: boolean
    isScannerSubmitting: boolean
    isScannerValid: boolean
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
    observationVerdictFilter: ObservationVerdictValue[]
    observations: ReplayObservationApi[]
    observationsLoading: boolean
    observationsPage: number
    observationsSort: ObservationsSorting | null
    observationsTotal: number
    onDemandObservationSuccessCount: number
    originalScanner: ScannerFormValues | null
    pollUntil: number
    retryingObservationIds: string[]
    savingCohortTag: string | null
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
    tagSuggestions: TagSuggestionApi[]
    tagSuggestionsLoading: boolean
    togglingEnabled: boolean
    triggeringOnDemandObservation: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayScannerLogicActions {
    acceptAllTagSuggestions: () => {
        value: true
    }
    acceptTagSuggestion: (tag: string) => {
        tag: string
    }
    appendClassifierTags: (tags: string[]) => {
        tags: string[]
    }
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
    dismissTagSuggestions: () => {
        value: true
    }
    draftScannerFromGoal: (
        goal: string,
        monthlyCreditBudget?: number
    ) => {
        goal: string
        monthlyCreditBudget: number | undefined
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
            goal: string
            monthlyCreditBudget: number | undefined
        }
    ) => {
        goalDraft: DraftScannerResponseApi | null
        payload?: {
            goal: string
            monthlyCreditBudget: number | undefined
        }
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
    loadTagSuggestions: () => any
    loadTagSuggestionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadTagSuggestionsSuccess: (
        tagSuggestions: TagSuggestionApi[],
        payload?: any
    ) => {
        tagSuggestions: TagSuggestionApi[]
        payload?: any
    }
    rebuildExperimentContext: () => {
        value: true
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
        verdict: ObservationVerdictValue[]
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
        verdict: ObservationVerdictValue[]
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
    saveAffectedCohort: (tag?: string) => {
        tag: string | undefined
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
            tag: string | undefined
        }
    ) => {
        affectedCohort: {
            cohort_id: number
        } | null
        payload?: {
            tag: string | undefined
        }
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
    setObservationVerdictFilter: (values: ObservationVerdictValue[]) => {
        values: ObservationVerdictValue[]
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
    startFromTemplate: (templateKey: string | null) => {
        templateKey: string | null
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
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface replayScannerLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isNew: (id: string) => boolean
        durationValidationError: (scanner: ScannerFormValues) => string | null
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
            observationBackfillFilter: string | null
        ) => boolean
        observationDetailLinkParams: (
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
            observationsSort: ObservationsSorting | null,
            scanner: ScannerFormValues
        ) => Record<string, number | string>
        availableTags: (observationStatsApi: ObservationStatsApi | null) => string[]
        observationStats: (observationStatsApi: ObservationStatsApi | null) => ObservationStatusStats
        sidePanelContext: (scanner: ScannerFormValues, isNew: boolean) => SidePanelSceneContext | null
        creditLimitState: (scanner: ScannerFormValues, scannerEstimate: EstimateResponseApi | null) => CreditLimitState
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
        loadScanner: true,
        loadScannerSuccess: (scanner: ScannerFormValues) => ({ scanner }),
        loadScannerFailure: true,
        // Background refetches use this instead of loadScannerSuccess, which also resets the form,
        // originalScanner, and submitIntent, and can refire the observation loads.
        scannerWatermarkRefreshed: (scanner: ReplayScanner) => ({ scanner }),
        setExperimentContext: (context: ExperimentScannerContext | null) => ({ context }),
        setExperimentVariant: (variantKey: string | null) => ({ variantKey }),
        detachExperimentContext: true,
        rebuildExperimentContext: true,
        saveAffectedCohort: (tag?: string) => ({ tag }),
        setScannerType: (scannerType: ScannerType) => ({ scannerType }),
        startFromTemplate: (templateKey: string | null) => ({ templateKey }),
        discardScannerDraft: true,
        setScannerDraftSavedAt: (savedAt: number | null) => ({ savedAt }),
        // Fired only after an actual API write, unlike submitScannerSuccess (which the advance path emits too).
        scannerSaved: (scanner: ScannerFormValues) => ({ scanner }),
        appendClassifierTags: (tags: string[]) => ({ tags }),
        clearClassifierTags: true,
        acceptTagSuggestion: (tag: string) => ({ tag }),
        acceptAllTagSuggestions: true,
        dismissTagSuggestions: true,
        draftScannerFromGoal: (goal: string, monthlyCreditBudget?: number) => ({ goal, monthlyCreditBudget }),
        setGoalDraftInput: (goal: string) => ({ goal }),
        setGoalBudgetInput: (budget: number | null) => ({ budget }),
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
        setObservationStatusFilter: (values: ObservationStatusValue[]) => ({ values }),
        setObservationTriggeredByFilter: (values: ObservationTriggeredByValue[]) => ({ values }),
        setObservationVerdictFilter: (values: ObservationVerdictValue[]) => ({ values }),
        setObservationTagFilter: (values: string[]) => ({ values }),
        setObservationScoreRange: (minScore: number | null, maxScore: number | null) => ({ minScore, maxScore }),
        setObservationSubjectFilter: (value: string) => ({ value }),
        setObservationDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setObservationBackfillFilter: (value: string | null) => ({ value }),
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

    forms(({ props, actions }) => ({
        scanner: {
            defaults: newScanner(
                props.id === 'new' ? currentTemplateKey() : null,
                teamLogic.findMounted()?.values.currentTeam?.name
            ),
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
                              'Enter a credit limit, or turn the limit off'
                            : scanner.credit_limit == null ||
                                (Number.isInteger(scanner.credit_limit) &&
                                    scanner.credit_limit >= 1 &&
                                    scanner.credit_limit <= MAX_CREDIT_LIMIT)
                              ? undefined
                              : `Credit limit must be a whole number between 1 and ${MAX_CREDIT_LIMIT.toLocaleString()}`,
                    scanner_config: Object.keys(configErrors).length > 0 ? configErrors : undefined,
                }
            },
            submit: async (scanner: ScannerFormValues) => {
                // A non-final step only ever offers "Next", so any submit there advances rather than persisting.
                // Enter would otherwise save an existing scanner and leave the wizard from the middle of it.
                const currentStep = scannerEditorSceneLogic.findMounted()?.values.step ?? 'configure'
                // The overview step sits outside the manual wizard's step list (indexOf -1), so its
                // submit must persist rather than resolve to the list's first step and navigate there.
                const currentStepIndex = SCANNER_EDITOR_STEPS.indexOf(currentStep)
                const nextStep = currentStepIndex === -1 ? undefined : SCANNER_EDITOR_STEPS[currentStepIndex + 1]
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
                        const response = await visionScannersCreate(String(teamId), scannerToApiBody(body))
                        actions.scannerSaved(scanner)
                        router.actions.replace(urls.replayVision(response.id))
                        // First scheduled results are minutes away, so the copy matches the Overview's
                        // pending panel and the button hands off to the instant on-demand tab.
                        lemonToast.success('Scanner created. First scan in progress.', {
                            button: {
                                label: 'Scan a recording now',
                                action: () => router.actions.push(`${urls.replayVision(response.id)}?tab=on-demand`),
                                dataAttr: 'vision-scanner-created-scan-now',
                            },
                        })
                    } else {
                        await visionScannersPartialUpdate(String(teamId), props.id, scannerToPatchedApiBody(body))
                        actions.scannerSaved(scanner)
                        lemonToast.success('Scanner saved')
                        router.actions.push(urls.replayVision(props.id))
                    }
                } catch (error: any) {
                    // A duplicate name is the one field error the details step can fix, so route back to it.
                    if (error.attr === 'name' && error.detail) {
                        actions.setScannerManualErrors({ name: error.detail })
                        router.actions.push(urls.replayVisionScannerDetails(props.id))
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
                saveAffectedCohort: async ({ tag }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || props.id === 'new') {
                        return values.affectedCohort
                    }
                    try {
                        const response = await visionScannersAffectedCohortCreate(
                            String(teamId),
                            props.id,
                            tag ? { tag } : {}
                        )
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
                draftScannerFromGoal: async ({ goal, monthlyCreditBudget }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId || !goal.trim()) {
                        return values.goalDraft
                    }
                    return await visionScannersDraftCreate(String(teamId), {
                        goal: goal.trim(),
                        ...(typeof monthlyCreditBudget === 'number' && monthlyCreditBudget > 0
                            ? { monthly_credit_budget: monthlyCreditBudget }
                            : {}),
                    })
                },
            },
        ],
        tagSuggestions: [
            [] as TagSuggestionApi[],
            {
                loadTagSuggestions: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    const scanner = values.scanner
                    if (!teamId || !scanner || scanner.scanner_type !== 'classifier') {
                        return []
                    }
                    const config = scanner.scanner_config
                    try {
                        const response = await visionScannersSuggestTagsCreate(String(teamId), {
                            prompt: config.prompt ?? '',
                            tags: config.tags ?? [],
                            multi_label: config.multi_label ?? true,
                            allow_freeform_tags: config.allow_freeform_tags ?? false,
                            scanner_id: props.id !== 'new' ? props.id : undefined,
                        })
                        return response.suggestions ?? []
                    } catch (error: any) {
                        lemonToast.error(`Couldn't generate suggestions${error?.detail ? `: ${error.detail}` : ''}`)
                        return []
                    }
                },
            },
        ],
    })),

    reducers({
        scannerDraftSavedAt: [
            null as number | null,
            {
                setScannerDraftSavedAt: (_, { savedAt }) => savedAt,
            },
        ],
        // The "tell PostHog AI what you want to accomplish" textarea on the template step.
        goalDraftInput: [
            '',
            {
                setGoalDraftInput: (_, { goal }) => goal,
                // Cleared once a draft or a template pick consumed it, so a stale goal doesn't linger.
                draftScannerFromGoalSuccess: () => '',
                startFromTemplate: () => '',
            },
        ],
        // The monthly credit budget input on the goal-based creation flow. Default 5,000 credits
        // (~$50): the round anchor the budget question shows, and enough for a real first scanner.
        goalBudgetInput: [
            5000 as number | null,
            {
                setGoalBudgetInput: (_, { budget }) => budget,
            },
        ],
        // A template pick replaces the drafted form, so its rationale no longer describes the config.
        goalDraft: [
            null as DraftScannerResponseApi | null,
            {
                startFromTemplate: () => null,
            },
        ],
        // Which tag's cohort is being created, so tag rows can show a per-row spinner.
        savingCohortTag: [
            null as string | null,
            {
                saveAffectedCohort: (_, { tag }) => tag ?? null,
                saveAffectedCohortSuccess: () => null,
                saveAffectedCohortFailure: () => null,
            },
        ],
        scanner: {
            // Only the sweep watermark lands, so a background refresh can't clobber unsaved form edits.
            scannerWatermarkRefreshed: (state: ReplayScanner, { scanner }: { scanner: ReplayScanner }) =>
                state ? { ...state, last_swept_at: scanner.last_swept_at } : scanner,
        },
        experimentContext: [
            null as ExperimentScannerContext | null,
            {
                setExperimentContext: (_, { context }) => context,
                setExperimentVariant: (state, { variantKey }) => (state ? { ...state, variantKey } : state),
                detachExperimentContext: () => null,
            },
        ],
        originalScanner: [
            null as ScannerFormValues | null,
            {
                loadScannerSuccess: (_, { scanner }) => scanner,
                // Keyed on the real save, not submitScannerSuccess — kea-forms fires that on the no-API advance path too.
                scannerSaved: (_, { scanner }) => scanner,
                toggleEnabledSuccess: (state, { enabled }) => (state ? { ...state, enabled } : state),
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
        tagSuggestions: {
            // Accepted suggestions leave the panel; the listener adds them to the vocabulary.
            acceptTagSuggestion: (state: TagSuggestionApi[], { tag }: { tag: string }) =>
                state.filter((s) => s.tag !== tag),
            dismissTagSuggestions: () => [],
        },
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
                backfillFilter: string | null
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
                backfillFilter !== null,
        ],
        // Carried into observation detail links so server-computed prev/next neighbors honor the table's filters + sort.
        observationDetailLinkParams: [
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
                s.observationsSort,
                s.scanner,
            ],
            (
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
                observationsSort: ObservationsSorting | null,
                scanner: ReplayScanner | null
            ): Record<string, string | number> =>
                buildObservationListParams({
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
                    observationsSort,
                    scanner,
                }) as Record<string, string | number>,
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
            (s) => [s.scanner, s.scannerEstimate],
            (scanner: ScannerFormValues | null, estimate: EstimateResponseApi | null): CreditLimitState => {
                const limit = typeof scanner?.credit_limit === 'number' ? scanner.credit_limit : null
                const estimatedMonthly = estimate?.estimated_credits_per_month ?? null
                const creditsPerObservation = estimate?.credits_per_observation ?? null
                return {
                    limit,
                    isOn: scanner?.credit_limit_enabled ?? limit !== null,
                    estimatedMonthly,
                    creditsPerObservation,
                    isBelowEstimate: limit !== null && estimatedMonthly !== null && limit < estimatedMonthly,
                    // A cap under one scan's cost never admits a single scan, so the scanner is stopped from
                    // the moment it is saved.
                    cannotAffordOneScan:
                        limit !== null && creditsPerObservation !== null && limit < creditsPerObservation,
                    // No estimate yet, or a zero one: null leaves the field empty rather than inventing a number.
                    seedValue:
                        estimatedMonthly !== null && estimatedMonthly > 0
                            ? Math.max(1, Math.round(estimatedMonthly * CREDIT_LIMIT_SEED_HEADROOM))
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
            actions.loadObservations(background)
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
            const savedAt = writeScannerDraft(teamId, values.scanner)
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
            // kea-forms' exact rejection for failed client-side validation. API failures toast in submit's catch.
            submitScannerFailure: async ({ error }) => {
                if (error?.message !== 'Validation Failed') {
                    return
                }
                const currentStep = scannerEditorSceneLogic.findMounted()?.values.step
                // Enter submits the whole form, so leaving a step that validates nothing must behave like
                // its Next button: move on, rather than red-flag fields the user has not reached yet.
                if (currentStep && UNVALIDATED_SCANNER_STEPS.includes(currentStep)) {
                    const next = SCANNER_EDITOR_STEPS[SCANNER_EDITOR_STEPS.indexOf(currentStep) + 1]
                    if (next) {
                        router.actions.push(scannerStepUrlWithParams(next, props.id, router.values.searchParams))
                    }
                    return
                }
                const erroredStep = firstErroredScannerStep({
                    ...values.scannerValidationErrors,
                    duration: values.durationValidationError,
                })
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
                    const urlTemplateKey = currentTemplateKey()
                    // A draft outranks the template param (it carries its own type and config), and an
                    // unknown template falls back to the from-scratch flow. Both present as custom, so
                    // strip the param so the URL matches what the user actually gets.
                    const templateKey =
                        !draft && urlTemplateKey && findScannerTemplate(urlTemplateKey) ? urlTemplateKey : null
                    const teamName = teamLogic.findMounted()?.values.currentTeam?.name
                    const experimentParams = parseExperimentScannerParams(router.values.searchParams)
                    const goalParam =
                        typeof router.values.searchParams.goal === 'string'
                            ? router.values.searchParams.goal.trim()
                            : ''
                    // Consumed unconditionally on every wizard entry: whichever prefill path wins
                    // below, a hand-off armed by the nudge must not stay usable for the rest of
                    // the tab session, where a later ?goal= link would auto-start a draft and
                    // spend the user's AI allowance without fresh intent.
                    const handedOffGoal = consumeGoalDraftIntent()?.trim() ?? ''
                    // Prefill precedence: an experiment deep link, then an explicit ?filters=
                    // query (both carry fully built state), then a saved draft, then the
                    // free-text goal. A URL carrying both ?filters= and ?goal= deterministically
                    // takes the filters and drops the goal.
                    const hasFiltersPrefill = 'filters' in router.values.searchParams
                    // Strip the params the wizard has now consumed so a reload doesn't re-run the prefill
                    // over the user's edits: an unknown template that fell back to from-scratch (a valid
                    // template stays), the experiment deep-link params, and the goal param. One replace
                    // covers all of them and preserves the URL hash, which a second back-to-back replace
                    // would drop.
                    const nextParams = { ...router.values.searchParams }
                    if (urlTemplateKey && !templateKey) {
                        delete nextParams.template
                    }
                    if (experimentParams) {
                        delete nextParams.experiment
                        delete nextParams.variant
                    }
                    if (nextParams.goal !== undefined) {
                        delete nextParams.goal
                    }
                    if (Object.keys(nextParams).length !== Object.keys(router.values.searchParams).length) {
                        router.actions.replace(router.values.location.pathname, nextParams, router.values.hashParams)
                    }
                    if (experimentParams) {
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
                            const prefilled = prefillScannerForExperiment(newScanner(templateKey, teamName), context)
                            // Set the context only after the prefill is built, so a throw inside it
                            // doesn't leave a dangling context that the next startFromTemplate re-applies.
                            actions.setExperimentContext(context)
                            actions.loadScannerSuccess(prefilled)
                        } catch {
                            // Clear any context a partial run left set before surfacing the failure.
                            actions.setExperimentContext(null)
                            lemonToast.error("Couldn't load the experiment. Set recording filters manually instead.")
                            actions.loadScannerSuccess(newScanner(templateKey, teamName))
                        } finally {
                            cache.restoringDraft = false
                        }
                        return
                    }
                    cache.restoringDraft = true
                    try {
                        actions.loadScannerSuccess(newScanner(templateKey, teamName))
                        if (draft) {
                            actions.setScannerValues(draft.scanner)
                            actions.setScannerDraftSavedAt(draft.savedAt)
                            // A draft made from an experiment prefill carries targeting the
                            // loadScannerSuccess above (a bare newScanner) didn't see.
                            actions.rebuildExperimentContext()
                        }
                    } finally {
                        cache.restoringDraft = false
                    }
                    // The goal prefills the AI box; the draft only auto-starts for the in-player
                    // nudge's sessionStorage hand-off (which carries the goal so the free text
                    // never enters the URL), and never over a saved draft. A crafted external
                    // ?goal= link can therefore neither spend the user's AI allowance nor
                    // overwrite saved work without an explicit click.
                    const goal = handedOffGoal || goalParam
                    if (goal && !hasFiltersPrefill) {
                        actions.setGoalDraftInput(goal)
                        if (handedOffGoal && !draft) {
                            actions.draftScannerFromGoal(handedOffGoal)
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
                if (values.observationsSort?.columnKey === 'result' && scanner.scanner_type) {
                    actions.loadObservations()
                    actions.loadObservationStats()
                }
                actions.rebuildExperimentContext()
            },

            // Rebuilds the targeting card from the form's current targeting — a loaded scanner or a
            // restored draft — so the variant picker and detach stay usable wherever it came from.
            // The API nulls experiment_targeting for viewers denied the experiment, so this never
            // fetches an experiment the viewer can't see. Fails soft: without the card the scanner
            // still edits normally.
            rebuildExperimentContext: async () => {
                const targeting = values.scanner?.experiment_targeting
                if (!targeting?.experiment_id || values.experimentContext) {
                    return
                }
                try {
                    const experiment = await api.experiments.get(targeting.experiment_id)
                    // The form's targeting can change while this request is in flight (a template pick or
                    // draft discard resets it), so re-check before installing the card. Otherwise a late
                    // response restores a card for targeting the scanner no longer carries, which a later
                    // variant change would then re-persist.
                    const current = values.scanner?.experiment_targeting
                    if (current?.experiment_id !== targeting.experiment_id || values.experimentContext) {
                        return
                    }
                    actions.setExperimentContext({ experiment, variantKey: current.variant ?? null })
                } catch {
                    // The card simply doesn't render; targeting stays intact on the scanner.
                }
            },

            // The reducer has already stored the new key; targeting lives in its own field, so a
            // variant change never touches `query` and filters the user added by hand survive.
            setExperimentVariant: () => {
                const context = values.experimentContext
                if (!context) {
                    return
                }
                actions.setScannerValue('experiment_targeting', buildExperimentTargeting(context))
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
                actions.resetScanner({
                    ...current,
                    name: keepsDefaultName ? defaultScannerName(teamName, scannerType) : current.name,
                    scanner_type: scannerType,
                    scanner_config: defaultConfigForType(scannerType),
                } as ScannerFormValues)
                persistDraft()
            },

            // Fires on request rather than result, so failed drafts still count as entering the AI path.
            draftScannerFromGoal: ({ goal, monthlyCreditBudget }) => {
                posthog.capture('replay_vision_scanner_creation_started', {
                    creation_method: 'ai',
                    template_key: null,
                    // The goal is customer text, so only its length is captured.
                    goal_length: goal.trim().length,
                })
                // Goal flow: land on the overview immediately, in its skeleton state, so the wait
                // reads as progress rather than a stuck button. A budget marks the goal flow; the
                // legacy AI box passes none and keeps opening the details step on success.
                if (monthlyCreditBudget != null) {
                    router.actions.push(urls.replayVisionScannerOverview('new'))
                }
            },

            // A successful AI draft seeds the wizard form, then the configure step opens for review.
            draftScannerFromGoalSuccess: ({ goalDraft }) => {
                if (!goalDraft) {
                    return
                }
                // The model call can take a while; if the user picked a template or navigated away
                // meanwhile, their newer state wins and the stale draft is dropped. The box lives on
                // the template step and the zero-scanner empty state; the goal flow has already moved
                // to the overview skeleton, so all three count as still there.
                const pathname = router.values.location.pathname
                if (
                    !pathname.endsWith(urls.replayVisionScannerTemplate('new')) &&
                    !pathname.endsWith(urls.replayVisionScannerOverview('new')) &&
                    !pathname.endsWith(urls.replayVision())
                ) {
                    return
                }
                actions.resetScanner(newScanner(null, teamLogic.values.currentTeam?.name))
                // Applied as form values (not baked into the reset) so the draft persists like hand-edited
                // input and survives a reload of the configure step.
                actions.setScannerValues({
                    name: goalDraft.name,
                    description: goalDraft.description,
                    scanner_type: goalDraft.scanner_type as ScannerType,
                    scanner_config: goalDraft.scanner_config as ScannerConfig,
                    // The drafted session filter (when the goal mapped to real screens or events); the
                    // triggers step shows it for review like any hand-picked filter.
                    ...(goalDraft.query ? { query: goalDraft.query as RecordingsQuery } : {}),
                    // A goal-flow draft also solves the budget dials; legacy drafts keep the wizard defaults.
                    ...(goalDraft.sampling_mode ? { sampling_mode: goalDraft.sampling_mode as SamplingMode } : {}),
                    ...(goalDraft.sampling_rate != null ? { sampling_rate: goalDraft.sampling_rate } : {}),
                    // The model the draft chose for the goal, and the credit cap set to the stated
                    // budget. credit_limit_enabled is UI-only form state, so turn it on alongside.
                    ...(goalDraft.model ? { model: goalDraft.model } : {}),
                    ...(goalDraft.credit_limit != null
                        ? { credit_limit: goalDraft.credit_limit, credit_limit_enabled: true }
                        : {}),
                })
                // Solved dials mark a goal-flow draft, which reviews on the overview; legacy drafts
                // open the details step. The goal flow is already on the overview (pushed on request),
                // so this only navigates the legacy path.
                const isGoalFlowDraft = goalDraft.sampling_mode != null || goalDraft.sampling_rate != null
                if (isGoalFlowDraft) {
                    // The form now carries the drafted filter, so count what it will actually watch.
                    actions.loadScannerEstimate()
                } else {
                    router.actions.push(urls.replayVisionScannerDetails('new'))
                }
            },

            draftScannerFromGoalFailure: ({ errorObject }) => {
                lemonToast.error(`Couldn't draft a scanner${errorObject?.detail ? `: ${errorObject.detail}` : ''}`)
                // The goal flow moved to the overview skeleton on request; with no draft to show,
                // send the user back to the questions to try again.
                if (router.values.location.pathname.endsWith(urls.replayVisionScannerOverview('new'))) {
                    router.actions.push(urls.replayVisionScannerTemplate('new'))
                }
            },

            // Merge AI-suggested tags into the vocabulary: keep existing tags, append new ones, dedupe case-insensitively.
            appendClassifierTags: ({ tags }) => {
                const scanner = values.scanner
                if (!scanner || scanner.scanner_type !== 'classifier') {
                    return
                }
                // Keep existing tags, append new ones, dedupe case-insensitively (existing tags win).
                const existing = scanner.scanner_config.tags ?? []
                const seen = new Set(existing.map((t) => t.toLowerCase()))
                const merged = [...existing]
                for (const tag of tags) {
                    const trimmed = tag.trim()
                    if (trimmed && !seen.has(trimmed.toLowerCase())) {
                        seen.add(trimmed.toLowerCase())
                        merged.push(trimmed)
                    }
                }
                if (merged.length !== existing.length) {
                    actions.setScannerValue(['scanner_config', 'tags'], merged)
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

            acceptTagSuggestion: ({ tag }) => actions.appendClassifierTags([tag]),
            acceptAllTagSuggestions: () => {
                // Read the suggestions before dismiss clears them.
                actions.appendClassifierTags(values.tagSuggestions.map((s) => s.tag))
                actions.dismissTagSuggestions()
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
            startFromTemplate: ({ templateKey }) => {
                // Counterpart of the AI capture, so the creation funnel can split by path.
                posthog.capture('replay_vision_scanner_creation_started', {
                    creation_method: templateKey ? 'template' : 'scratch',
                    template_key: templateKey,
                })
                clearScannerDraft()
                actions.setScannerDraftSavedAt(null)
                // An experiment prefill (targeted query, scoped name) has to survive the template
                // reset, so re-apply it when the wizard was entered from an experiment.
                const base = newScanner(templateKey, teamLogic.values.currentTeam?.name)
                const context = values.experimentContext
                actions.resetScanner(context ? prefillScannerForExperiment(base, context) : base)
            },
            discardScannerDraft: () => {
                // Storage holds one draft, and it belongs to the new-scanner wizard.
                if (props.id === 'new') {
                    clearScannerDraft()
                    actions.setScannerDraftSavedAt(null)
                }
                // Discarding ends the experiment flow; a scanner started next must not inherit it.
                actions.setExperimentContext(null)
                actions.resetScanner(values.originalScanner ?? newScanner(null))
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
                    const response = await visionScannersEstimateCreate(String(teamId), {
                        query: scanner.query ?? undefined,
                        // Sent alongside the query so the preview counts the same exposed-person
                        // population the scan will, instead of every eligible session.
                        experiment_targeting: scanner.experiment_targeting ?? null,
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
        const buildSearchParams = (): Record<string, string | undefined> => {
            const next = { ...router.values.searchParams } as Record<string, string | undefined>
            for (const key of TABLE_URL_PARAM_KEYS) {
                delete next[key]
            }
            if (values.observationsPage > 1) {
                next.page = String(values.observationsPage)
            }
            const sort = values.observationsSort
            next.sort = serializeSortParam(sort, { columnKey: 'created_at', order: -1 })
            Object.assign(next, observationFilterParams(values))
            return next
        }
        const writeUrl = (): [string, Record<string, string | undefined>] => [
            router.values.location.pathname,
            buildSearchParams(),
        ]
        // Replace (not push) so typing in the subject search doesn't spam browser history.
        const writeUrlReplace = (): [
            string,
            Record<string, string | undefined>,
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
            setObservationSubjectFilter: writeUrlReplace,
            clearObservationFilters: writeUrl,
        }
    }),

    urlToAction(({ actions, values, props }) => ({
        // Restore as one atomic action (individual setters would reset the page); dispatch only on actual change.
        [urls.replayVision(props.id)]: (_, searchParams) => {
            const pageRaw = Number(searchParams.page ?? 1)
            const page = Number.isFinite(pageRaw) ? Math.max(1, pageRaw) : 1
            const sort = parseSortParam(searchParams.sort) ?? { columnKey: 'created_at', order: -1 }
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
                backfillId === values.observationBackfillFilter
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
            actions.loadObservations()
            actions.loadObservationStats()
        }
    }),

    beforeUnmount(({ values, props, cache }) => {
        if (props.id === 'new' && cache.draftTouched && values.scannerDraftSavedAt !== null) {
            // Back to the step the last edit was on, not always the first one — returning to details
            // after editing recordings or budget reads as having lost those steps, even though the
            // values were restored. The template step holds no edits, so it falls through to details.
            const step = cache.lastEditedStep
            const resumeUrl = scannerStepUrl(step && step !== 'template' ? step : 'details', 'new')
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

const TABLE_URL_PARAM_KEYS = [
    'page',
    'sort',
    'status',
    'triggered_by',
    'verdict',
    'tags',
    'min_score',
    'max_score',
    'recording_subject',
    'date_from',
    'date_to',
    'backfill_id',
] as const

/** Observation-filter params the scanner page reads from the URL; links into the Observations tab build from these keys. */
export type ObservationsUrlParams = Partial<Record<(typeof TABLE_URL_PARAM_KEYS)[number], string>>

/** The step URLs of a scanner's editor wizard. */
function scannerEditorPaths(scannerId: string): string[] {
    return [
        ...SCANNER_EDITOR_STEPS.map((step) => scannerStepUrl(step, scannerId)),
        // The goal flow's overview step is editor territory too, though it sits outside the manual stepper.
        scannerStepUrl('overview', scannerId),
        // Retired step: the redirect off it must not trip the unsaved-changes guard.
        urls.replayVisionScannerSelfDriving(scannerId),
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
}): boolean {
    const { hasUnsavedChanges, isSubmitting, hasSavedDraft, scannerId, currentPathname, nextPathname } = params
    if (!hasUnsavedChanges || isSubmitting || hasSavedDraft) {
        return false
    }
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
