import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'
import { objectsEqual } from 'lib/utils/objects'

import { AggregatedSpanRow, DateRange } from '~/queries/schema/schema-general'

import { type DurationHistogramRow, pivotDurationHistogram, type TracingDurationHistogramData } from './durationBuckets'
import { type DurationRange, operationFilterGroup } from './operationFilters'
import { traceLookupDateRange } from './traceLinks'
import { isUserInitiatedError, NEW_QUERY_STARTED_ERROR_MESSAGE } from './tracingDataLogic'
import { DEFAULT_DATE_RANGE } from './tracingFiltersLogic'
import type { tracingOperationSceneLogicType } from './tracingOperationSceneLogicType'
import type { Span } from './types'

export interface TracingOperationSceneLogicProps {
    serviceName: string
    spanName: string
}

const SAMPLE_LIMIT = 100

// One tracked AbortController per loader: re-issuing a fetch aborts the superseded request
// (not just discards its result), and unmount aborts whatever is still in flight.
function trackedSignal(cache: Record<string, any>, key: string): AbortSignal {
    let controller!: AbortController
    cache.disposables.add(
        () => {
            controller = new AbortController()
            return () => controller.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
        },
        key,
        // In-flight requests must survive tab switches — only supersession or unmount aborts.
        { pauseOnPageHidden: false }
    )
    return controller.signal
}

export const tracingOperationSceneLogic = kea<tracingOperationSceneLogicType>([
    props({} as TracingOperationSceneLogicProps),
    key(({ serviceName, spanName }) => `${serviceName}//${spanName}`),
    path((key) => ['products', 'tracing', 'frontend', 'tracingOperationSceneLogic', key]),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setDurationSelection: (selection: DurationRange | null) => ({ selection }),
        setSampleIndex: (index: number) => ({ index }),
        selectSpan: (spanId: string | null) => ({ spanId }),
        setSamplesHaveMore: (hasMore: boolean) => ({ hasMore }),
        loadCurrentSampleTrace: true,
    }),

    loaders(({ props, values, actions, cache }) => ({
        rawHistogram: [
            [] as DurationHistogramRow[],
            {
                fetchHistogram: async (_: void, breakpoint) => {
                    await breakpoint(10) // coalesce same-tick dispatches (URL restore + afterMount)
                    const response = await api.tracing.durationHistogram(
                        {
                            dateRange: values.dateRange,
                            serviceNames: [props.serviceName],
                            filterGroup: operationFilterGroup(props.spanName, null),
                            // Span-level: operations are often child spans, and the samples query
                            // below is span-level too — both must count the same population.
                            rootSpans: false,
                        },
                        trackedSignal(cache, 'fetchHistogram')
                    )
                    breakpoint()
                    return response.results
                },
            },
        ],
        samples: [
            [] as Span[],
            {
                fetchSamples: async (_: void, breakpoint) => {
                    await breakpoint(10) // coalesce same-tick dispatches (URL restore + afterMount)
                    const response = await api.tracing.listSpans(
                        {
                            dateRange: values.dateRange,
                            orderBy: 'timestamp',
                            orderDirection: 'DESC',
                            serviceNames: [props.serviceName],
                            filterGroup: operationFilterGroup(props.spanName, values.durationSelection),
                            flatSpans: true,
                            limit: SAMPLE_LIMIT,
                            // Samples only feed the pager header (5 scalar fields); the waterfall
                            // loads the full trace separately, so skip the heavy attribute maps.
                            excludeAttributes: true,
                        },
                        trackedSignal(cache, 'fetchSamples')
                    )
                    breakpoint()
                    actions.setSamplesHaveMore(!!response.hasMore)
                    return response.results as Span[]
                },
            },
        ],
        operationStats: [
            null as AggregatedSpanRow | null,
            {
                fetchStats: async (_: void, breakpoint) => {
                    await breakpoint(10) // coalesce same-tick dispatches (URL restore + afterMount)
                    const response = await api.tracing.aggregate(
                        {
                            dateRange: values.dateRange,
                            serviceNames: [props.serviceName],
                            filterGroup: operationFilterGroup(props.spanName, null),
                        },
                        trackedSignal(cache, 'fetchStats')
                    )
                    breakpoint()
                    return response.results.find((row) => row.name === props.spanName) ?? null
                },
            },
        ],
        sampleTraceSpans: [
            [] as Span[],
            {
                fetchSampleTrace: async ({ sample }: { sample: Span }, breakpoint) => {
                    await breakpoint(100) // debounce rapid pager clicks
                    const response = await api.tracing.getTrace(
                        sample.trace_id,
                        {
                            dateRange: traceLookupDateRange(sample.timestamp),
                        },
                        trackedSignal(cache, 'fetchSampleTrace')
                    )
                    breakpoint()
                    return response.results as Span[]
                },
            },
        ],
    })),

    reducers({
        dateRange: [DEFAULT_DATE_RANGE as DateRange, { setDateRange: (_, { dateRange }) => dateRange }],
        durationSelection: [null as DurationRange | null, { setDurationSelection: (_, { selection }) => selection }],
        sampleIndex: [
            0,
            {
                setSampleIndex: (_, { index }) => index,
                setDurationSelection: () => 0,
                setDateRange: () => 0,
            },
        ],
        selectedSpanId: [null as string | null, { selectSpan: (_, { spanId }) => spanId }],
        samplesHaveMore: [false, { setSamplesHaveMore: (_, { hasMore }) => hasMore }],
        // A stale waterfall must not linger under a new (or empty) sample set.
        sampleTraceSpans: { fetchSamples: () => [] },
    }),

    selectors({
        serviceName: [() => [(_, props) => props.serviceName], (serviceName: string): string => serviceName],
        spanName: [() => [(_, props) => props.spanName], (spanName: string): string => spanName],
        histogramData: [
            (s) => [s.rawHistogram],
            (rows: DurationHistogramRow[]): TracingDurationHistogramData => pivotDurationHistogram(rows, dataColorVars),
        ],
        currentSample: [
            (s) => [s.samples, s.sampleIndex],
            (samples: Span[], sampleIndex: number): Span | null => samples[sampleIndex] ?? null,
        ],
    }),

    listeners(({ actions, values }) => ({
        setDurationSelection: () => {
            actions.fetchSamples()
        },
        setDateRange: () => {
            actions.fetchHistogram()
            actions.fetchSamples()
            actions.fetchStats()
        },
        loadCurrentSampleTrace: () => {
            const sample = values.currentSample
            if (!sample) {
                return
            }
            // Adjacent samples often share a trace (a child operation hit N times per request) —
            // re-anchor on the already-loaded trace instead of refetching it.
            if (values.sampleTraceSpans[0]?.trace_id === sample.trace_id) {
                actions.selectSpan(sample.span_id)
                return
            }
            actions.fetchSampleTrace({ sample })
        },
        fetchSamplesSuccess: ({ samples }) => {
            if (samples.length === 0) {
                actions.selectSpan(null)
                return
            }
            if (values.sampleIndex >= samples.length) {
                // A deep-linked or stale index past the new result set would render a blank sample.
                actions.setSampleIndex(0)
                return
            }
            actions.loadCurrentSampleTrace()
        },
        setSampleIndex: () => {
            // While samples are (re)loading, the index points into the outgoing result set;
            // fetchSamplesSuccess (or fetchSamplesFailure) loads the trace for the resolved index.
            if (values.samplesLoading) {
                return
            }
            actions.loadCurrentSampleTrace()
        },
        fetchSampleTraceSuccess: () => {
            // Anchor the waterfall on the operation's own span — for child operations the
            // sample sits deep in a larger trace and would otherwise open unfocused at the root.
            actions.selectSpan(values.currentSample?.span_id ?? null)
        },
        fetchHistogramFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load latency distribution: ${error}`)
            }
        },
        fetchSamplesFailure: ({ error }) => {
            if (isUserInitiatedError(error)) {
                return
            }
            lemonToast.error(`Failed to load sample traces: ${error}`)
            // The failed refetch already blanked the waterfall (see the sampleTraceSpans reducer);
            // reload the trace for the retained samples so the scene stays usable.
            actions.loadCurrentSampleTrace()
        },
        fetchStatsFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load operation stats: ${error}`)
            }
        },
        fetchSampleTraceFailure: ({ error }) => {
            if (!isUserInitiatedError(error)) {
                lemonToast.error(`Failed to load trace: ${error}`)
            }
        },
    })),

    actionToUrl(({ values }) => {
        const withSelectionParams = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { min, max, sample, dateRange, ...rest } = router.values.searchParams
            const params: Record<string, any> = { ...rest }
            if (!objectsEqual(values.dateRange, DEFAULT_DATE_RANGE)) {
                params.dateRange = JSON.stringify(values.dateRange)
            }
            if (values.durationSelection) {
                params.min = values.durationSelection.minNs
                params.max = values.durationSelection.maxNs
            }
            if (values.sampleIndex > 0) {
                params.sample = values.sampleIndex
            }
            return [router.values.location.pathname, params, router.values.hashParams, { replace: true }]
        }
        return {
            setDateRange: withSelectionParams,
            setDurationSelection: withSelectionParams,
            setSampleIndex: withSelectionParams,
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/tracing/operation': (_, searchParams, __, { method }) => {
            if (method === 'REPLACE') {
                return // our own actionToUrl writes
            }
            // Restore the date range first: setDateRange resets sampleIndex.
            if (searchParams.dateRange) {
                try {
                    const dateRange =
                        typeof searchParams.dateRange === 'string'
                            ? JSON.parse(searchParams.dateRange)
                            : searchParams.dateRange
                    if (!objectsEqual(dateRange, values.dateRange)) {
                        actions.setDateRange(dateRange)
                    }
                } catch {
                    // Malformed param — keep the current range.
                }
            }
            const minNs = parseInt(String(searchParams.min), 10)
            const maxNs = parseInt(String(searchParams.max), 10)
            const selection = !isNaN(minNs) && !isNaN(maxNs) ? { minNs, maxNs } : null
            if (!objectsEqual(selection, values.durationSelection)) {
                actions.setDurationSelection(selection)
            }
            const sample = parseInt(String(searchParams.sample), 10)
            if (!isNaN(sample) && sample >= 0 && sample !== values.sampleIndex) {
                actions.setSampleIndex(sample)
            }
        },
    })),

    afterMount(({ actions, props }) => {
        // A malformed link renders the scene's missing-params fallback; don't query for it.
        if (!props.spanName || !props.serviceName) {
            return
        }
        // URL restore may have dispatched these already in this same tick — the loaders'
        // leading breakpoint coalesces the duplicates into one request each.
        actions.fetchHistogram()
        actions.fetchStats()
        actions.fetchSamples()
    }),
])
