import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { FilterLogicalOperator } from '~/types'

import type { logsServicesLogicType } from './logsServicesLogicType'

export interface ServiceRow {
    service_name: string
    log_count: number
    error_count: number
    error_rate: number
    volume_share_pct?: number
    severity_breakdown?: {
        debug: number
        info: number
        warn: number
        error: number
    }
    active_rules?: { rule_id: string; rule_name: string; summary_string: string }[]
}

export interface ServiceSparklinePoint {
    time: string
    service_name: string
    count: number
}

export interface ServicesResponse {
    services: ServiceRow[]
    sparkline: ServiceSparklinePoint[]
    summary?: {
        top_services_count: number
        top_services_volume_share_pct: number
    }
}

export const logsServicesLogic = kea<logsServicesLogicType>([
    path(['products', 'logs', 'frontend', 'components', 'LogsServices', 'logsServicesLogic']),

    actions({
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
    }),

    reducers({
        dateFrom: [
            '-24h' as string,
            {
                setDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
    }),

    loaders(({ values }) => ({
        servicesData: [
            { services: [], sparkline: [], summary: undefined } as ServicesResponse,
            {
                loadServicesData: async () => {
                    const response = await api.logs.services({
                        query: {
                            dateRange: { date_from: values.dateFrom },
                            severityLevels: [],
                            filterGroup: { type: FilterLogicalOperator.And, values: [] },
                            serviceNames: [],
                        },
                    })
                    return response
                },
            },
        ],
    })),

    selectors({
        services: [(s) => [s.servicesData], (data: ServicesResponse): ServiceRow[] => data.services],

        servicesSummary: [(s) => [s.servicesData], (data: ServicesResponse) => data.summary],

        sparklineByService: [
            (s) => [s.servicesData],
            (data: ServicesResponse): Record<string, { values: number[]; labels: string[] }> => {
                const byService: Record<string, Map<string, number>> = {}
                const allTimes = new Set<string>()

                for (const point of data.sparkline) {
                    allTimes.add(point.time)
                    if (!byService[point.service_name]) {
                        byService[point.service_name] = new Map()
                    }
                    byService[point.service_name].set(point.time, point.count)
                }

                const sortedTimes = Array.from(allTimes).sort()
                const result: Record<string, { values: number[]; labels: string[] }> = {}

                for (const [serviceName, timeMap] of Object.entries(byService)) {
                    result[serviceName] = {
                        values: sortedTimes.map((t) => timeMap.get(t) ?? 0),
                        labels: sortedTimes,
                    }
                }

                return result
            },
        ],
    }),

    listeners(({ actions }) => ({
        setDateFrom: () => {
            actions.loadServicesData()
        },
    })),

    afterMount(({ actions }) => {
        actions.loadServicesData()
    }),
])
