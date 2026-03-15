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
                const response = await api.tracing.listSpans()
                return response.results as Span[]
            },
        },
        traceSpans: {
            __default: [] as Span[],
            loadTraceSpans: async (traceId: string): Promise<Span[]> => {
                const response = await api.tracing.getTrace(traceId)
                return response.results as Span[]
            },
        },
        sparklineRows: {
            __default: [] as SparklineRow[],
            loadSparkline: async (): Promise<SparklineRow[]> => {
                const response = await api.tracing.sparkline()
                return response.results as SparklineRow[]
            },
        },
    }),

    selectors({
        sparklineData: [
            (s) => [s.sparklineRows],
            (rows: SparklineRow[]): TracingSparklineData => {
                if (!rows.length) {
                    return { data: [], dates: [] }
                }

                const timeBuckets = [...new Set(rows.map((r) => r.time))].sort()
                const services = [...new Set(rows.map((r) => r.service))].sort()

                const countMap = new Map<string, number>()
                for (const row of rows) {
                    countMap.set(`${row.time}|${row.service}`, row.count)
                }

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
        actions.loadSparkline()
    }),
])
