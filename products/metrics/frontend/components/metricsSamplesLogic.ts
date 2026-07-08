import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { teamLogic } from 'scenes/teamLogic'

import { metricsSamplesCreate } from 'products/metrics/frontend/generated/api'
import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { DEFAULT_METRICS_DATE_FROM, resolveMetricsDate } from './metricsDates'
import type { metricsSamplesLogicType } from './metricsSamplesLogicType'
import { metricsViewerLogic } from './metricsViewerLogic'

export const DEFAULT_SAMPLES_LIMIT = 100
const NEW_QUERY_STARTED_ERROR_MESSAGE = 'A new metric samples query started, cancelling the previous one'

export const metricsSamplesLogic = kea<metricsSamplesLogicType>([
    path(['products', 'metrics', 'frontend', 'components', 'metricsSamplesLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            metricsViewerLogic,
            ['metricName as viewerMetricName', 'dateFrom as viewerDateFrom', 'dateTo as viewerDateTo'],
        ],
    })),
    actions({
        setMetricName: (metricName: string) => ({ metricName }),
        setDateFrom: (dateFrom: string | null) => ({ dateFrom }),
        setDateTo: (dateTo: string | null) => ({ dateTo }),
        setTraceId: (traceId: string) => ({ traceId }),
        setLimit: (limit: number) => ({ limit }),
        setServiceFilter: (serviceFilter: string[]) => ({ serviceFilter }),
        setSamplesAbortController: (controller: AbortController | null) => ({ controller }),
        cancelInProgressSamplesQuery: (controller: AbortController | null) => ({ controller }),
    }),
    reducers({
        metricName: ['' as string, { setMetricName: (_, { metricName }) => metricName }],
        dateFrom: [DEFAULT_METRICS_DATE_FROM as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        dateTo: [null as string | null, { setDateTo: (_, { dateTo }) => dateTo }],
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        limit: [DEFAULT_SAMPLES_LIMIT as number, { setLimit: (_, { limit }) => limit }],
        serviceFilter: [[] as string[], { setServiceFilter: (_, { serviceFilter }) => serviceFilter }],
        samplesAbortController: [
            null as AbortController | null,
            { setSamplesAbortController: (_, { controller }) => controller },
        ],
    }),
    loaders(({ values, actions }) => ({
        samples: [
            [] as _MetricEventSampleApi[],
            {
                fetchSamples: async (_, breakpoint) => {
                    const trimmedName = values.metricName.trim()
                    if (!trimmedName) {
                        return []
                    }
                    const dateFromISO = resolveMetricsDate(values.dateFrom)
                    if (!dateFromISO) {
                        return []
                    }
                    await breakpoint(300)
                    const dateToISO = resolveMetricsDate(values.dateTo) ?? undefined
                    const trimmedTraceId = values.traceId.trim()
                    const controller = new AbortController()
                    actions.cancelInProgressSamplesQuery(controller)
                    const response = await metricsSamplesCreate(
                        String(values.currentTeamId),
                        {
                            query: {
                                metricName: trimmedName,
                                dateFrom: dateFromISO,
                                ...(dateToISO ? { dateTo: dateToISO } : {}),
                                ...(trimmedTraceId ? { traceId: trimmedTraceId } : {}),
                                limit: values.limit,
                            },
                        },
                        { signal: controller.signal }
                    )
                    breakpoint()
                    actions.setSamplesAbortController(null)
                    return response.results
                },
            },
        ],
    })),
    selectors({
        hasMetricName: [(s) => [s.metricName], (metricName) => metricName.trim().length > 0],
        serviceOptions: [
            (s) => [s.samples],
            (samples): string[] =>
                Array.from(new Set(samples.map((sample) => sample.service_name).filter(Boolean))).sort(),
        ],
        filteredSamples: [
            (s) => [s.samples, s.serviceFilter],
            (samples, serviceFilter): _MetricEventSampleApi[] =>
                serviceFilter.length
                    ? samples.filter((sample) => serviceFilter.includes(sample.service_name))
                    : samples,
        ],
    }),
    listeners(({ actions, values }) => ({
        setMetricName: () => actions.fetchSamples({}),
        setDateFrom: () => actions.fetchSamples({}),
        setDateTo: () => actions.fetchSamples({}),
        setTraceId: () => actions.fetchSamples({}),
        setLimit: () => actions.fetchSamples({}),
        cancelInProgressSamplesQuery: ({ controller }) => {
            if (values.samplesAbortController !== null) {
                values.samplesAbortController.abort(NEW_QUERY_STARTED_ERROR_MESSAGE)
            }
            actions.setSamplesAbortController(controller)
        },
    })),
    afterMount(({ actions, values }) => {
        if (!values.metricName && values.viewerMetricName) {
            actions.setDateFrom(values.viewerDateFrom)
            actions.setDateTo(values.viewerDateTo)
            actions.setMetricName(values.viewerMetricName)
        } else {
            actions.fetchSamples({})
        }
    }),
])
