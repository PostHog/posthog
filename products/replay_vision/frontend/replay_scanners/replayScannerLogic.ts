import { actions, afterMount, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { objectsEqual } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'

import {
    visionScannersCreate,
    visionScannersDestroy,
    visionScannersEstimateCreate,
    visionScannersObservationsList,
    visionScannersPartialUpdate,
    visionScannersRetrieve,
} from '../generated/api'
import type { EstimateResponseApi, ReplayObservationApi } from '../generated/api.schemas'
import { scheduleObservationPoll } from '../logics/observationPolling'
import { readFixedTags, readFreeformTags, readModelOutput, readTags, readVerdict } from '../utils/observation'
import type { replayScannerLogicType } from './replayScannerLogicType'
import { findScannerTemplate } from './scannerTemplates'
import {
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    ScannerConfig,
    ScannerType,
    ReplayScanner,
    scannerFromApi,
    scannerToApiBody,
    scannerToPatchedApiBody,
} from './types'

export interface ReplayScannerLogicProps {
    id: string
    tabId: string
}

export type ObservationStatusValue = ReplayObservationApi['status']
export type ObservationTriggeredByValue = ReplayObservationApi['triggered_by']
export type ObservationVerdictValue = 'yes' | 'no' | 'inconclusive'

function quantile(sorted: number[], q: number): number {
    if (sorted.length === 1) {
        return sorted[0]
    }
    const pos = (sorted.length - 1) * q
    const lo = Math.floor(pos)
    const hi = Math.ceil(pos)
    return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo)
}

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

function newScanner(templateKey?: string | null): ReplayScanner {
    const base = {
        id: 'new',
        enabled: true,
        sampling_rate: 1,
        query: { kind: NodeKind.RecordingsQuery },
        provider: DEFAULT_PROVIDER,
        model: DEFAULT_MODEL,
        emits_signals: false,
        scanner_version: 1,
        last_swept_at: dayjs().toISOString(),
        created_at: dayjs().toISOString(),
        updated_at: dayjs().toISOString(),
        created_by: null,
    } as const

    const template = findScannerTemplate(templateKey ?? undefined)
    if (template) {
        return {
            ...base,
            name: template.scanner_name,
            description: template.scanner_description,
            scanner_type: template.scanner_type,
            scanner_config: template.scanner_config,
        } as ReplayScanner
    }
    return {
        ...base,
        name: '',
        description: '',
        scanner_type: 'monitor',
        scanner_config: { prompt: '' },
    }
}

export const replayScannerLogic = kea<replayScannerLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerLogic']),
    props({} as ReplayScannerLogicProps),
    key((props) => `${props.tabId}:${props.id}`),

    actions({
        loadScanner: true,
        loadScannerSuccess: (scanner: ReplayScanner) => ({ scanner }),
        loadScannerFailure: true,
        setScannerType: (scannerType: ScannerType) => ({ scannerType }),
        loadObservations: true,
        loadObservationsSuccess: (observations: ReplayObservationApi[]) => ({ observations }),
        loadObservationsFailure: true,
        deleteScanner: true,
        setObservationStatusFilter: (values: ObservationStatusValue[]) => ({ values }),
        setObservationTriggeredByFilter: (values: ObservationTriggeredByValue[]) => ({ values }),
        setObservationVerdictFilter: (values: ObservationVerdictValue[]) => ({ values }),
        setObservationTagFilter: (values: string[]) => ({ values }),
        clearObservationFilters: true,
        setChartDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        requestScannerEstimate: true,
        loadScannerEstimate: true,
        loadScannerEstimateSuccess: (estimate: EstimateResponseApi) => ({ estimate }),
        loadScannerEstimateFailure: true,
    }),

    forms(({ props }) => ({
        scanner: {
            defaults: newScanner(props.id === 'new' ? currentTemplateKey() : null),
            errors: (scanner: ReplayScanner) => {
                const configErrors: Record<string, string | undefined> = {}
                if (!scanner.scanner_config?.prompt?.trim()) {
                    configErrors.prompt = 'Prompt is required'
                }
                if (scanner.scanner_type === 'scorer') {
                    const { min, max } = scanner.scanner_config.scale
                    if (typeof min !== 'number' || typeof max !== 'number' || min >= max) {
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
                    }
                } catch (error) {
                    lemonToast.error(`Failed to save scanner: ${String(error)}`)
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
        observationsLoading: [
            false,
            {
                loadObservations: () => true,
                loadObservationsSuccess: () => false,
                loadObservationsFailure: () => false,
            },
        ],
        scannerEstimate: [
            null as EstimateResponseApi | null,
            {
                loadScannerEstimateSuccess: (_, { estimate }) => estimate,
                loadScannerEstimateFailure: () => null,
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
            },
        ],
        observationTriggeredByFilter: [
            [] as ObservationTriggeredByValue[],
            {
                setObservationTriggeredByFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
            },
        ],
        observationVerdictFilter: [
            [] as ObservationVerdictValue[],
            {
                setObservationVerdictFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
            },
        ],
        observationTagFilter: [
            [] as string[],
            {
                setObservationTagFilter: (_, { values }) => values,
                clearObservationFilters: () => [],
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
            (s) => [s.observations],
            (observations: ReplayObservationApi[]): boolean =>
                observations.some((o) => o.status === 'pending' || o.status === 'running'),
        ],
        filteredObservations: [
            (s) => [
                s.observations,
                s.observationStatusFilter,
                s.observationTriggeredByFilter,
                s.observationVerdictFilter,
                s.observationTagFilter,
            ],
            (
                observations: ReplayObservationApi[],
                statusFilter: ObservationStatusValue[],
                triggeredByFilter: ObservationTriggeredByValue[],
                verdictFilter: ObservationVerdictValue[],
                tagFilter: string[]
            ): ReplayObservationApi[] => {
                return observations.filter((o) => {
                    if (statusFilter.length > 0 && !statusFilter.includes(o.status)) {
                        return false
                    }
                    if (triggeredByFilter.length > 0 && !triggeredByFilter.includes(o.triggered_by)) {
                        return false
                    }
                    if (verdictFilter.length > 0) {
                        const verdict = readVerdict(o)
                        if (verdict === null || !verdictFilter.includes(verdict)) {
                            return false
                        }
                    }
                    if (tagFilter.length > 0) {
                        const present = readTags(o)
                        if (!tagFilter.some((t) => present.includes(t))) {
                            return false
                        }
                    }
                    return true
                })
            },
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
            (s) => [s.observations],
            (observations: ReplayObservationApi[]): string[] => {
                const set = new Set<string>()
                for (const obs of observations) {
                    for (const tag of readTags(obs)) {
                        set.add(tag)
                    }
                }
                return Array.from(set).sort()
            },
        ],
        observationStats: [
            (s) => [s.observations],
            (
                observations: ReplayObservationApi[]
            ): {
                total: number
                succeeded: number
                failed: number
                ineligible: number
                inFlight: number
                successRate: number | null
            } => {
                let succeeded = 0
                let failed = 0
                let ineligible = 0
                let inFlight = 0
                for (const o of observations) {
                    if (o.status === 'succeeded') {
                        succeeded += 1
                    } else if (o.status === 'failed') {
                        failed += 1
                    } else if (o.status === 'ineligible') {
                        ineligible += 1
                    } else {
                        inFlight += 1
                    }
                }
                // Success rate excludes ineligible: those were skipped at the gate, not scanner failures.
                const scored = succeeded + failed
                return {
                    total: observations.length,
                    succeeded,
                    failed,
                    ineligible,
                    inFlight,
                    successRate: scored > 0 ? Math.round((succeeded / scored) * 100) : null,
                }
            },
        ],
        succeededObservations: [
            (s) => [s.observations],
            (observations: ReplayObservationApi[]): ReplayObservationApi[] =>
                observations.filter((o) => o.status === 'succeeded'),
        ],
        monitorStats: [
            (s) => [s.succeededObservations],
            (
                observations: ReplayObservationApi[]
            ): { yesTotal: number; noTotal: number; inconclusiveTotal: number } => {
                let yesTotal = 0
                let noTotal = 0
                let inconclusiveTotal = 0
                for (const obs of observations) {
                    const v = readVerdict(obs)
                    if (v === 'yes') {
                        yesTotal += 1
                    } else if (v === 'no') {
                        noTotal += 1
                    } else if (v === 'inconclusive') {
                        inconclusiveTotal += 1
                    }
                }
                return { yesTotal, noTotal, inconclusiveTotal }
            },
        ],
        classifierTagStats: [
            (s) => [s.succeededObservations],
            (
                observations: ReplayObservationApi[]
            ): {
                fixedRanked: [string, number][]
                freeformRanked: [string, number][]
                totalWithTags: number
            } => {
                const fixedCounts = new Map<string, number>()
                const freeformCounts = new Map<string, number>()
                let totalWithTags = 0
                for (const obs of observations) {
                    const fixed = readFixedTags(obs)
                    const freeform = readFreeformTags(obs)
                    if (fixed.length === 0 && freeform.length === 0) {
                        continue
                    }
                    totalWithTags += 1
                    for (const tag of fixed) {
                        fixedCounts.set(tag, (fixedCounts.get(tag) ?? 0) + 1)
                    }
                    for (const tag of freeform) {
                        freeformCounts.set(tag, (freeformCounts.get(tag) ?? 0) + 1)
                    }
                }
                const rank = (counts: Map<string, number>): [string, number][] =>
                    Array.from(counts.entries())
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 10)
                return { fixedRanked: rank(fixedCounts), freeformRanked: rank(freeformCounts), totalWithTags }
            },
        ],
        scorerScores: [
            (s) => [s.succeededObservations],
            (observations: ReplayObservationApi[]): number[] => {
                const items: number[] = []
                for (const obs of observations) {
                    const out = readModelOutput(obs)
                    if (out && typeof out.score === 'number') {
                        items.push(out.score)
                    }
                }
                items.sort((a, b) => a - b)
                return items
            },
        ],
        scorerSummary: [
            (s) => [s.scorerScores],
            (
                scores: number[]
            ): { min: number; p25: number; median: number; mean: number; p75: number; max: number } | null => {
                if (scores.length === 0) {
                    return null
                }
                return {
                    min: scores[0],
                    p25: quantile(scores, 0.25),
                    median: quantile(scores, 0.5),
                    mean: scores.reduce((a, b) => a + b, 0) / scores.length,
                    p75: quantile(scores, 0.75),
                    max: scores[scores.length - 1],
                }
            },
        ],
        // Score histogram: count of observations per score bucket across the configured scale.
        scorerHistogram: [
            (s) => [s.scorerScores, s.scanner],
            (scores: number[], scanner: ReplayScanner | null): { labels: string[]; counts: number[] } | null => {
                if (scores.length === 0) {
                    return null
                }
                // Span the configured scale (falling back to the observed range) so the axis shows the full
                // possible range even when scores cluster. Widen the bucket for large scales to cap the bar count.
                const scale = scanner?.scanner_type === 'scorer' ? scanner.scanner_config.scale : undefined
                const lo = Math.floor(scale?.min ?? scores[0])
                const hi = Math.ceil(scale?.max ?? scores[scores.length - 1])
                const span = Math.max(0, hi - lo)
                const bucketWidth = Math.max(1, Math.ceil((span + 1) / 21))
                const bucketCount = Math.floor(span / bucketWidth) + 1
                const counts = new Array(bucketCount).fill(0)
                for (const score of scores) {
                    const idx = Math.min(
                        bucketCount - 1,
                        Math.max(0, Math.floor((Math.round(score) - lo) / bucketWidth))
                    )
                    counts[idx] += 1
                }
                const labels = counts.map((_, i) => {
                    const start = lo + i * bucketWidth
                    return bucketWidth === 1 ? String(start) : `${start}–${Math.min(start + bucketWidth - 1, hi)}`
                })
                return { labels, counts }
            },
        ],
        // Distinct sessions scanned: last 14 days and total. Surfaces sweep-job coverage.
        coverageStats: [
            (s) => [s.observations],
            (
                observations: ReplayObservationApi[]
            ): { recentSessions: number; totalSessions: number; recentDays: number } => {
                const cutoff = dayjs().subtract(14, 'day')
                const recent = new Set<string>()
                const all = new Set<string>()
                for (const obs of observations) {
                    if (!obs.session_id) {
                        continue
                    }
                    all.add(obs.session_id)
                    if (dayjs(obs.created_at).isAfter(cutoff)) {
                        recent.add(obs.session_id)
                    }
                }
                return { recentSessions: recent.size, totalSessions: all.size, recentDays: 14 }
            },
        ],
    }),

    listeners(({ actions, props, values, cache }) => ({
        loadScanner: async () => {
            if (props.id === 'new') {
                actions.loadScannerSuccess(newScanner(currentTemplateKey()))
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersRetrieve(String(teamId), props.id)
                actions.loadScannerSuccess(scannerFromApi(response))
            } catch (error) {
                lemonToast.error(`Failed to load scanner: ${String(error)}`)
                actions.loadScannerFailure()
                router.actions.replace(urls.replayVision())
            }
        },

        loadScannerSuccess: ({ scanner }) => {
            actions.setScannerValues(scanner)
            actions.requestScannerEstimate()
        },

        setScannerType: ({ scannerType }) => {
            actions.setScannerValues({ scanner_type: scannerType, scanner_config: defaultConfigForType(scannerType) })
        },

        // kea-forms fires setScannerValue(s) on every field change. Debounce the estimate so slider drags
        // and rapid filter edits don't fire one request per tick.
        setScannerValue: () => actions.requestScannerEstimate(),
        setScannerValues: () => actions.requestScannerEstimate(),
        submitScannerSuccess: () => actions.requestScannerEstimate(),

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
            } catch (error) {
                if (error instanceof Error && isBreakpoint(error)) {
                    throw error
                }
                // eslint-disable-next-line no-console
                console.warn('[replay-vision] scanner estimate failed', error)
                actions.loadScannerEstimateFailure()
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
            } catch (error) {
                lemonToast.error(`Failed to delete scanner: ${String(error)}`)
            }
        },

        loadObservations: async () => {
            if (props.id === 'new') {
                actions.loadObservationsSuccess([])
                return
            }
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            try {
                const response = await visionScannersObservationsList(String(teamId), props.id)
                actions.loadObservationsSuccess(response.results ?? [])
            } catch {
                actions.loadObservationsFailure()
            }
        },

        loadObservationsSuccess: () => {
            scheduleObservationPoll(cache.disposables, values.hasObservationsInFlight, actions.loadObservations)
        },
    })),

    afterMount(({ actions, props }) => {
        actions.loadScanner()
        if (props.id !== 'new') {
            actions.loadObservations()
        }
    }),
])
