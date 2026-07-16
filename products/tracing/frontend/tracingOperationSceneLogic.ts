import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dataColorVars } from 'lib/colors'

import { AggregatedSpanRow, DateRange } from '~/queries/schema/schema-general'

import { type DurationHistogramRow, pivotDurationHistogram, type TracingDurationHistogramData } from './durationBuckets'
import { type DurationRange, operationFilterGroup } from './operationFilters'
import { traceLookupDateRange } from './traceLinks'
import { DEFAULT_DATE_RANGE } from './tracingFiltersLogic'
import type { tracingOperationSceneLogicType } from './tracingOperationSceneLogicType'
import type { Span } from './types'

export interface TracingOperationSceneLogicProps {
    serviceName: string
    spanName: string
}

const SAMPLE_LIMIT = 100

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
    }),

    loaders(({ props, values, actions }) => ({
        rawHistogram: [
            [] as DurationHistogramRow[],
            {
                fetchHistogram: async (_: void, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.tracing.durationHistogram({
                        dateRange: values.dateRange,
                        serviceNames: [props.serviceName],
                        filterGroup: operationFilterGroup(props.spanName, null),
                        // Span-level: operations are often child spans, and the samples query
                        // below is span-level too — both must count the same population.
                        rootSpans: false,
                    })
                    breakpoint()
                    return response.results
                },
            },
        ],
        samples: [
            [] as Span[],
            {
                fetchSamples: async (_: void, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.tracing.listSpans({
                        dateRange: values.dateRange,
                        orderBy: 'timestamp',
                        orderDirection: 'DESC',
                        serviceNames: [props.serviceName],
                        filterGroup: operationFilterGroup(props.spanName, values.durationSelection),
                        flatSpans: true,
                        limit: SAMPLE_LIMIT,
                    })
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
                    await breakpoint(100)
                    const response = await api.tracing.aggregate({
                        dateRange: values.dateRange,
                        serviceNames: [props.serviceName],
                        filterGroup: operationFilterGroup(props.spanName, null),
                    })
                    breakpoint()
                    return response.results.find((row) => row.name === props.spanName) ?? null
                },
            },
        ],
        sampleTraceSpans: [
            [] as Span[],
            {
                fetchSampleTrace: async ({ sample }: { sample: Span }, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.tracing.getTrace(sample.trace_id, {
                        dateRange: traceLookupDateRange(sample.timestamp),
                    })
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
            if (values.currentSample) {
                actions.fetchSampleTrace({ sample: values.currentSample })
            }
        },
        setSampleIndex: () => {
            if (values.currentSample) {
                actions.fetchSampleTrace({ sample: values.currentSample })
            }
        },
        fetchSampleTraceSuccess: () => {
            // Anchor the waterfall on the operation's own span — for child operations the
            // sample sits deep in a larger trace and would otherwise open unfocused at the root.
            actions.selectSpan(values.currentSample?.span_id ?? null)
        },
        fetchHistogramFailure: ({ error }) => {
            lemonToast.error(`Failed to load latency distribution: ${error}`)
        },
        fetchSamplesFailure: ({ error }) => {
            lemonToast.error(`Failed to load sample traces: ${error}`)
        },
        fetchStatsFailure: ({ error }) => {
            lemonToast.error(`Failed to load operation stats: ${error}`)
        },
        fetchSampleTraceFailure: ({ error }) => {
            lemonToast.error(`Failed to load trace: ${error}`)
        },
    })),

    actionToUrl(({ values }) => {
        const withSelectionParams = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { min, max, sample, ...rest } = router.values.searchParams
            const params: Record<string, any> = { ...rest }
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
            setDurationSelection: withSelectionParams,
            setSampleIndex: withSelectionParams,
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/tracing/operation': (_, searchParams, __, { method }) => {
            if (method === 'REPLACE') {
                return // our own actionToUrl writes
            }
            const minNs = parseInt(String(searchParams.min), 10)
            const maxNs = parseInt(String(searchParams.max), 10)
            const selection = !isNaN(minNs) && !isNaN(maxNs) ? { minNs, maxNs } : null
            if (JSON.stringify(selection) !== JSON.stringify(values.durationSelection)) {
                actions.setDurationSelection(selection)
            }
            const sample = parseInt(String(searchParams.sample), 10)
            if (!isNaN(sample) && sample >= 0 && sample !== values.sampleIndex) {
                actions.setSampleIndex(sample)
            }
        },
    })),

    afterMount(({ actions, values }) => {
        actions.fetchHistogram()
        actions.fetchStats()
        // A deep link restores the selection via urlToAction, whose listener already fetches
        // samples — only fetch directly when mounting without one.
        if (!values.durationSelection) {
            actions.fetchSamples()
        }
    }),
])
