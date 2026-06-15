import equal from 'fast-deep-equal'
import { actions, afterMount, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    visionScannersCreate,
    visionScannersDestroy,
    visionScannersEstimateCreate,
    visionScannersObservationsList,
    visionScannersObservationsStatsRetrieve,
    visionScannersObserveCreate,
    visionScannersPartialUpdate,
    visionScannersRetrieve,
} from '../generated/api'
import type { EstimateResponseApi, ObservationStatsApi, ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import type { replayScannerLogicType } from './replayScannerLogicType'
import { findScannerTemplate, newScanner } from './scannerTemplates'
import {
    ScannerConfig,
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

export const OBSERVATIONS_PAGE_SIZE = 50

const OBSERVE_POLL_GRACE_MS = 30_000

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

const UNIT_BY_LETTER: Record<string, dayjs.ManipulateType> = {
    h: 'hour',
    d: 'day',
    w: 'week',
    m: 'month',
    y: 'year',
}

const START_OF_BY_PREFIX: Record<string, dayjs.ManipulateType> = {
    dStart: 'day',
    wStart: 'week',
    mStart: 'month',
    yStart: 'year',
}

function chartRangeToDayjs(expr: string): dayjs.Dayjs | null {
    const relative = expr.match(/^-(\d+)([hdwmy])(Start|End)?$/)
    if (relative) {
        const [, n, letter, suffix] = relative
        const unit = UNIT_BY_LETTER[letter]
        const date = dayjs().subtract(parseInt(n, 10), unit)
        if (suffix === 'Start') {
            return date.startOf(unit)
        }
        if (suffix === 'End') {
            return date.endOf(unit)
        }
        return date
    }
    if (expr in START_OF_BY_PREFIX) {
        return dayjs().startOf(START_OF_BY_PREFIX[expr])
    }
    if (expr === 'all') {
        return dayjs().subtract(1, 'year')
    }
    const parsed = dayjs(expr)
    return parsed.isValid() ? parsed : null
}

function daysFromChartRange(dateFrom: string | null, dateTo: string | null): number {
    if (!dateFrom) {
        return 14
    }
    const from = chartRangeToDayjs(dateFrom)
    if (!from) {
        return 14
    }
    const to = dateTo ? chartRangeToDayjs(dateTo) || dayjs() : dayjs()
    return Math.max(1, to.diff(from, 'day'))
}

interface ObservationListParams {
    limit?: number
    offset?: number
    status?: string
    triggered_by?: string
    verdict?: string
    tags?: string
    order_by?: string
}

export interface ObservationsSorting {
    columnKey: string
    order: 1 | -1
}

const STATIC_ORDER_KEYS: Record<string, string> = {
    created_at: 'created_at',
    version: 'scanner_version',
}
// Only monitor and scorer have a JSONB-backed Result sort key on the server.
const RESULT_ORDER_KEY_BY_TYPE: Partial<Record<ScannerType, string>> = {
    scorer: 'result_score',
    monitor: 'result_verdict',
}

function resolveOrderByKey(columnKey: string, scannerType: ScannerType | undefined): string | null {
    if (columnKey === 'result') {
        return (scannerType && RESULT_ORDER_KEY_BY_TYPE[scannerType]) ?? null
    }
    return STATIC_ORDER_KEYS[columnKey] ?? null
}

/** Translate kea filter + sort state into the query params accepted by the list and stats endpoints. */
export function buildObservationListParams(
    values: {
        observationStatusFilter: ObservationStatusValue[]
        observationTriggeredByFilter: ObservationTriggeredByValue[]
        observationVerdictFilter: ObservationVerdictValue[]
        observationTagFilter: string[]
        observationsSort: ObservationsSorting | null
        scanner: ReplayScanner | null
    },
    limit?: number,
    offset?: number
): ObservationListParams {
    const params: ObservationListParams = {}
    if (limit !== undefined) {
        params.limit = limit
    }
    if (offset !== undefined && offset > 0) {
        params.offset = offset
    }
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
    if (values.observationsSort) {
        const orderKey = resolveOrderByKey(values.observationsSort.columnKey, values.scanner?.scanner_type)
        if (orderKey) {
            params.order_by = values.observationsSort.order === -1 ? `-${orderKey}` : orderKey
        }
    }
    return params
}

export const replayScannerLogic = kea<replayScannerLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerLogic']),
    props({} as ReplayScannerLogicProps),
    key((props) => props.id),

    actions({
        loadScanner: true,
        loadScannerSuccess: (scanner: ReplayScanner) => ({ scanner }),
        loadScannerFailure: true,
        setScannerType: (scannerType: ScannerType) => ({ scannerType }),
        setSubmitIntent: (intent: 'save' | 'advance') => ({ intent }),
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservationApi[], total: number) => ({ observations, total }),
        loadObservationsFailure: true,
        setObservationsPage: (page: number) => ({ page }),
        setObservationsSort: (sorting: ObservationsSorting | null) => ({ sorting }),
        loadObservationStats: true,
        loadObservationStatsSuccess: (stats: ObservationStatsApi) => ({ stats }),
        loadObservationStatsFailure: true,
        deleteScanner: true,
        toggleEnabled: true,
        toggleEnabledSuccess: (enabled: boolean) => ({ enabled }),
        toggleEnabledFailure: true,
        setObservationStatusFilter: (values: ObservationStatusValue[]) => ({ values }),
        setObservationTriggeredByFilter: (values: ObservationTriggeredByValue[]) => ({ values }),
        setObservationVerdictFilter: (values: ObservationVerdictValue[]) => ({ values }),
        setObservationTagFilter: (values: string[]) => ({ values }),
        clearObservationFilters: true,
        restoreObservationsTableState: (state: {
            page: number
            sort: ObservationsSorting | null
            status: ObservationStatusValue[]
            triggeredBy: ObservationTriggeredByValue[]
            verdict: ObservationVerdictValue[]
            tags: string[]
        }) => state,
        setChartDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        requestScannerEstimate: true,
        loadScannerEstimate: true,
        loadScannerEstimateSuccess: (estimate: EstimateResponseApi) => ({ estimate }),
        loadScannerEstimateFailure: (error: string | null = null) => ({ error }),
        triggerOnDemandObservation: (sessionId: string) => ({ sessionId }),
        triggerOnDemandObservationSuccess: true,
        triggerOnDemandObservationFailure: true,
        refreshObservations: true,
    }),

    forms(({ props, values, actions }) => ({
        scanner: {
            defaults: newScanner(props.id === 'new' ? currentTemplateKey() : null),
            errors: (scanner: ReplayScanner) => {
                const configErrors: Record<string, string | undefined> = {}
                if (!scanner.scanner_config?.prompt?.trim()) {
                    configErrors.prompt = 'Prompt is required'
                }
                if (scanner.scanner_type === 'classifier') {
                    const tags = scanner.scanner_config.tags ?? []
                    if (tags.length === 0) {
                        configErrors.tags = 'Add at least one tag to the vocabulary'
                    } else if (tags.some((t) => !t.trim())) {
                        configErrors.tags = "Tags can't be blank"
                    } else if (new Set(tags.map((t) => t.trim().toLowerCase())).size !== tags.length) {
                        configErrors.tags = 'Tags must be unique'
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
                    name: !scanner.name?.trim() ? 'Name is required' : undefined,
                    sampling_rate:
                        scanner.sampling_rate > 0 && scanner.sampling_rate <= 1
                            ? undefined
                            : 'Sampling rate must be between 0% and 100%',
                    scanner_config: Object.keys(configErrors).length > 0 ? configErrors : undefined,
                }
            },
            submit: async (scanner: ReplayScanner) => {
                if (values.submitIntent === 'advance') {
                    actions.setSubmitIntent('save')
                    router.actions.push(urls.replayVisionScannerTriggers(props.id))
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                const body = scanner.query == null ? omitQuery(scanner) : scanner
                try {
                    if (props.id === 'new') {
                        const response = await visionScannersCreate(String(teamId), scannerToApiBody(body))
                        router.actions.replace(urls.replayVision(response.id))
                        lemonToast.success('Scanner created')
                    } else {
                        await visionScannersPartialUpdate(String(teamId), props.id, scannerToPatchedApiBody(body))
                        lemonToast.success('Scanner saved')
                        router.actions.push(urls.replayVision(props.id))
                    }
                } catch (error: any) {
                    lemonToast.error(`Failed to save scanner${error.detail ? `: ${error.detail}` : ''}`)
                    throw error
                }
            },
        },
    })),

    reducers({
        originalScanner: [
            null as ReplayScanner | null,
            {
                loadScannerSuccess: (_, { scanner }) => scanner,
                submitScannerSuccess: (_, { scanner }: { scanner: ReplayScanner }) => scanner,
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
            },
        ],
        refreshing: [
            false,
            {
                refreshObservations: () => true,
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
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
        submitIntent: [
            'save' as 'save' | 'advance',
            {
                setSubmitIntent: (_, { intent }) => intent,
                loadScannerSuccess: () => 'save' as 'save' | 'advance',
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
                loadObservations: () => true,
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
        chartDateFrom: ['-14d' as string | null, { setChartDateRange: (_, { dateFrom }) => dateFrom }],
        chartDateTo: [null as string | null, { setChartDateRange: (_, { dateTo }) => dateTo }],
    }),

    selectors({
        isNew: [(_, p) => [p.id], (id: string) => id === 'new'],
        hasUnsavedChanges: [
            (s) => [s.scanner, s.originalScanner],
            (scanner: ReplayScanner | null, original: ReplayScanner | null): boolean => {
                if (!scanner || !original) {
                    return false
                }
                return !objectsEqual(scanner, original)
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
            ],
            (
                statusFilter: ObservationStatusValue[],
                triggeredByFilter: ObservationTriggeredByValue[],
                verdictFilter: ObservationVerdictValue[],
                tagFilter: string[]
            ): boolean =>
                statusFilter.length > 0 ||
                triggeredByFilter.length > 0 ||
                verdictFilter.length > 0 ||
                tagFilter.length > 0,
        ],
        availableTags: [
            (s) => [s.observationStatsApi],
            (stats: ObservationStatsApi | null): string[] => stats?.available_tags ?? [],
        ],
        observationStats: [
            (s) => [s.observationStatsApi],
            (
                stats: ObservationStatsApi | null
            ): {
                total: number
                succeeded: number
                failed: number
                ineligible: number
                inFlight: number
                successRate: number | null
            } => {
                if (!stats) {
                    return { total: 0, succeeded: 0, failed: 0, ineligible: 0, inFlight: 0, successRate: null }
                }
                const c = stats.status_counts
                return {
                    total: c.total,
                    succeeded: c.succeeded,
                    failed: c.failed,
                    ineligible: c.ineligible,
                    inFlight: c.in_flight,
                    successRate: c.success_rate,
                }
            },
        ],
        monitorStats: [
            (s) => [s.observationStatsApi],
            (stats: ObservationStatsApi | null): { yesTotal: number; noTotal: number; inconclusiveTotal: number } => ({
                yesTotal: stats?.monitor?.yes_total ?? 0,
                noTotal: stats?.monitor?.no_total ?? 0,
                inconclusiveTotal: stats?.monitor?.inconclusive_total ?? 0,
            }),
        ],
        classifierTagStats: [
            (s) => [s.observationStatsApi],
            (
                stats: ObservationStatsApi | null
            ): {
                fixedRanked: [string, number][]
                freeformRanked: [string, number][]
                totalWithTags: number
            } => ({
                fixedRanked: (stats?.classifier?.fixed_ranked ?? []).map((t) => [t.tag, t.count] as [string, number]),
                freeformRanked: (stats?.classifier?.freeform_ranked ?? []).map(
                    (t) => [t.tag, t.count] as [string, number]
                ),
                totalWithTags: stats?.classifier?.total_with_tags ?? 0,
            }),
        ],
        scorerSummary: [
            (s) => [s.observationStatsApi],
            (
                stats: ObservationStatsApi | null
            ): {
                min: number
                p25: number
                median: number
                mean: number
                p75: number
                max: number
                count: number
            } | null => stats?.scorer?.summary ?? null,
        ],
        scorerHistogram: [
            (s) => [s.observationStatsApi],
            (stats: ObservationStatsApi | null): { labels: string[]; counts: number[] } | null =>
                stats?.scorer?.histogram ?? null,
        ],
        coverageStats: [
            (s) => [s.observationStatsApi],
            (
                stats: ObservationStatsApi | null
            ): { recentSessions: number; totalSessions: number; recentDays: number } => ({
                recentSessions: stats?.coverage.recent_sessions ?? 0,
                totalSessions: stats?.coverage.total_sessions ?? 0,
                recentDays: stats?.coverage.recent_days ?? 14,
            }),
        ],
    }),

    listeners(({ actions, props, values, cache }) => {
        const reloadObservationsAndStats = (): void => {
            actions.loadObservations()
            actions.loadObservationStats()
        }
        return {
            loadScanner: async () => {
                if (props.id === 'new') {
                    const templateKey = currentTemplateKey()
                    if (templateKey && !findScannerTemplate(templateKey)) {
                        // Unknown template (stale link, typo, renamed key). Strip it so the URL matches
                        // what the user actually gets: the from-scratch flow with a selectable type.
                        const { template: _drop, ...rest } = router.values.searchParams
                        router.actions.replace(router.values.location.pathname, rest)
                        actions.loadScannerSuccess(newScanner(null))
                        return
                    }
                    actions.loadScannerSuccess(newScanner(templateKey))
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                try {
                    const response = await visionScannersRetrieve(String(teamId), props.id)
                    actions.loadScannerSuccess(scannerFromApi(response))
                } catch (error: any) {
                    lemonToast.error(`Failed to load scanner${error.detail ? `: ${error.detail}` : ''}`)
                    actions.loadScannerFailure()
                    router.actions.replace(urls.replayVision())
                }
            },

            loadScannerSuccess: ({ scanner }) => {
                actions.setScannerValues(scanner)
                actions.requestScannerEstimate()
                // A deep-link to `?sort=result` can't resolve its order_by until the scanner type is known;
                // refire once we have it so the initial paint reflects the URL.
                if (values.observationsSort?.columnKey === 'result' && scanner.scanner_type) {
                    actions.loadObservations()
                    actions.loadObservationStats()
                }
            },

            setScannerType: ({ scannerType }) => {
                const current = values.scanner
                if (!current) {
                    return
                }
                actions.resetScanner({
                    ...current,
                    scanner_type: scannerType,
                    scanner_config: defaultConfigForType(scannerType),
                } as ReplayScanner)
            },

            // kea-forms fires setScannerValue(s) on every field change. Debounce the estimate so slider drags
            // and rapid filter edits don't fire one request per tick.
            setScannerValue: () => actions.requestScannerEstimate(),
            setScannerValues: () => actions.requestScannerEstimate(),
            submitScannerSuccess: () => {
                actions.requestScannerEstimate()
                // Saving recomputes the persisted estimate, which shifts the org-wide fleet sum.
                visionQuotaLogic.findMounted()?.actions.loadQuota()
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
                        sampling_rate: scanner.sampling_rate,
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

            deleteScanner: async () => {
                if (props.id === 'new') {
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                try {
                    await visionScannersDestroy(String(teamId), props.id)
                    lemonToast.success('Scanner deleted')
                    router.actions.replace(urls.replayVision())
                } catch (error: any) {
                    lemonToast.error(`Failed to delete scanner${error.detail ? `: ${error.detail}` : ''}`)
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
                    visionQuotaLogic.findMounted()?.actions.loadQuota()
                } catch (error: any) {
                    actions.setScannerValue('enabled', !next)
                    const verb = next ? 'enable' : 'disable'
                    lemonToast.error(`Failed to ${verb} scanner${error.detail ? `: ${error.detail}` : ''}`)
                    actions.toggleEnabledFailure()
                }
            },

            triggerOnDemandObservation: async ({ sessionId }) => {
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
                    lemonToast.success('Scanning session — new observation will appear below shortly.')
                    actions.triggerOnDemandObservationSuccess()
                    actions.refreshObservations()
                } catch (error: any) {
                    lemonToast.error(`Failed to scan session${error.detail ? `: ${error.detail}` : ''}`)
                    actions.triggerOnDemandObservationFailure()
                }
            },

            refreshObservations: () => reloadObservationsAndStats(),

            loadObservations: async () => {
                if (props.id === 'new') {
                    actions.loadObservationsSuccess([], 0)
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                try {
                    const offset = (values.observationsPage - 1) * OBSERVATIONS_PAGE_SIZE
                    const params = buildObservationListParams(values, OBSERVATIONS_PAGE_SIZE, offset)
                    const response = await visionScannersObservationsList(String(teamId), props.id, params)
                    actions.loadObservationsSuccess(response.results ?? [], response.count ?? 0)
                } catch {
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
            clearObservationFilters: () => reloadObservationsAndStats(),

            setChartDateRange: () => {
                actions.loadObservationStats()
            },

            loadObservationStats: async () => {
                if (props.id === 'new') {
                    actions.loadObservationStatsFailure()
                    return
                }
                const teamId = teamLogic.values.currentTeamId
                if (!teamId) {
                    return
                }
                try {
                    // Stats endpoint accepts the same filters as the list, but `order_by` is meaningless on an aggregate.
                    const { order_by: _ignored, ...params } = buildObservationListParams(values)
                    const recentDays = daysFromChartRange(values.chartDateFrom, values.chartDateTo)
                    const response = await visionScannersObservationsStatsRetrieve(String(teamId), props.id, {
                        ...params,
                        recent_days: recentDays,
                    })
                    actions.loadObservationStatsSuccess(response)
                } catch {
                    actions.loadObservationStatsFailure()
                }
            },

            loadObservationStatsSuccess: () => {
                scheduleObservationPoll(
                    cache.disposables,
                    values.hasObservationsInFlight || Date.now() < values.pollUntil,
                    reloadObservationsAndStats
                )
            },
            // Reschedule on failure too — a transient API hiccup shouldn't permanently kill the polling cycle.
            loadObservationStatsFailure: () => {
                scheduleObservationPoll(
                    cache.disposables,
                    values.hasObservationsInFlight || Date.now() < values.pollUntil,
                    reloadObservationsAndStats
                )
            },
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
            if (sort && !(sort.columnKey === 'created_at' && sort.order === -1)) {
                next.sort = `${sort.order === -1 ? '-' : ''}${sort.columnKey}`
            }
            if (values.observationStatusFilter.length > 0) {
                next.status = values.observationStatusFilter.join(',')
            }
            if (values.observationTriggeredByFilter.length > 0) {
                next.triggered_by = values.observationTriggeredByFilter.join(',')
            }
            if (values.observationVerdictFilter.length > 0) {
                next.verdict = values.observationVerdictFilter.join(',')
            }
            if (values.observationTagFilter.length > 0) {
                next.tags = values.observationTagFilter.join(',')
            }
            return next
        }
        const writeUrl = (): [string, Record<string, string | undefined>] => [
            router.values.location.pathname,
            buildSearchParams(),
        ]
        return {
            setObservationsPage: writeUrl,
            setObservationsSort: writeUrl,
            setObservationStatusFilter: writeUrl,
            setObservationTriggeredByFilter: writeUrl,
            setObservationVerdictFilter: writeUrl,
            setObservationTagFilter: writeUrl,
            clearObservationFilters: writeUrl,
        }
    }),

    urlToAction(({ actions, values, props }) => ({
        // Restore as a single atomic action so the page reducer isn't reset by individual filter setters.
        // Idempotent: we only dispatch when something actually differs from current state.
        [urls.replayVision(props.id)]: (_, searchParams) => {
            const pageRaw = Number(searchParams.page ?? 1)
            const page = Number.isFinite(pageRaw) ? Math.max(1, pageRaw) : 1
            const sort = parseSortParam(searchParams.sort) ?? { columnKey: 'created_at', order: -1 }
            const status = parseCsvParam<ObservationStatusValue>(searchParams.status)
            const triggeredBy = parseCsvParam<ObservationTriggeredByValue>(searchParams.triggered_by)
            const verdict = parseCsvParam<ObservationVerdictValue>(searchParams.verdict)
            const tags = parseCsvParam<string>(searchParams.tags)
            const sameAsCurrent =
                page === values.observationsPage &&
                sort.columnKey === values.observationsSort?.columnKey &&
                sort.order === values.observationsSort?.order &&
                equal(status, values.observationStatusFilter) &&
                equal(triggeredBy, values.observationTriggeredByFilter) &&
                equal(verdict, values.observationVerdictFilter) &&
                equal(tags, values.observationTagFilter)
            if (!sameAsCurrent) {
                actions.restoreObservationsTableState({ page, sort, status, triggeredBy, verdict, tags })
            }
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadScanner()
        if (props.id !== 'new') {
            actions.loadObservations()
            actions.loadObservationStats()
        }
    }),
])

const TABLE_URL_PARAM_KEYS = ['page', 'sort', 'status', 'triggered_by', 'verdict', 'tags'] as const

export function parseSortParam(value: string | undefined): ObservationsSorting | null {
    if (typeof value !== 'string' || value.length === 0) {
        return null
    }
    const descending = value.startsWith('-')
    const columnKey = descending ? value.slice(1) : value
    if (!columnKey) {
        return null
    }
    return { columnKey, order: descending ? -1 : 1 }
}

export function parseCsvParam<T extends string>(value: string | undefined): T[] {
    if (typeof value !== 'string' || value.length === 0) {
        return []
    }
    return value
        .split(',')
        .map((v) => v.trim())
        .filter((v) => v.length > 0) as T[]
}
