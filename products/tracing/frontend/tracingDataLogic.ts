import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { getSeriesColor } from 'lib/colors'

import type { tracingDataLogicType } from './tracingDataLogicType'
import type { Span } from './types'

export interface SparklineRow {
    time: string
    service: string
    count: number
}

export interface TracingSparklineData {
    data: { name: string; values: number[]; color: string }[]
    dates: string[]
}

export const tracingDataLogic = kea<tracingDataLogicType>([
    path(['products', 'tracing', 'frontend', 'tracingDataLogic']),

    loaders({
        spans: {
            __default: [] as Span[],
            loadSpans: async (): Promise<Span[]> => {
                const response = await api.tracing.listSpans({
                    dateRange: { date_from: '-1h' },
                    orderBy: 'latest',
                    limit: 100,
                })
                return response.results as Span[]
            },
        },
        traceSpans: {
            __default: [] as Span[],
            loadTraceSpans: async (traceId: string): Promise<Span[]> => {
                const response = await api.tracing.getTrace(traceId, { date_from: '-24h' })
                return response.results as Span[]
            },
        },
    }),

    selectors({
        sparklineData: [
            (s) => [s.spans],
            (spans: Span[]): TracingSparklineData => {
                if (!spans.length) {
                    return { data: [], dates: [] }
                }

                const bucketMinutes = 5
                const countMap = new Map<string, number>()
                const timeBucketsSet = new Set<string>()
                const servicesSet = new Set<string>()

                for (const span of spans) {
                    const ts = new Date(span.timestamp)
                    ts.setSeconds(0, 0)
                    ts.setMinutes(Math.floor(ts.getMinutes() / bucketMinutes) * bucketMinutes)
                    const bucket = ts.toISOString()
                    timeBucketsSet.add(bucket)
                    servicesSet.add(span.service_name)
                    const key = `${bucket}|${span.service_name}`
                    countMap.set(key, (countMap.get(key) ?? 0) + 1)
                }

                const timeBuckets = [...timeBucketsSet].sort()
                const services = [...servicesSet].sort()

                const data = services.map((service, i) => ({
                    name: service,
                    values: timeBuckets.map((t) => countMap.get(`${t}|${service}`) ?? 0),
                    color: getSeriesColor(i),
                }))

                return { data, dates: timeBuckets }
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadSpans()
    }),
])
