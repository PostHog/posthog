import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { dateStringToDayJs } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    EndpointsUsageBreakdown,
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { EndpointType, IntervalType } from '~/types'

import { endpointsLogic } from './endpointsLogic'
import type { endpointsUsageLogicType } from './endpointsUsageLogicType'

export const INITIAL_DATE_FROM = '-7d'
export const INITIAL_DATE_TO = null as string | null
export const INITIAL_INTERVAL: IntervalType = 'day'

export interface EndpointsUsageLogicProps {
    tabId: string
}

export const endpointsUsageLogic = kea<endpointsUsageLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointsUsageLogic']),
    props({} as EndpointsUsageLogicProps),
    key((props) => props.tabId),
    connect(({ tabId }: EndpointsUsageLogicProps) => ({
        values: [endpointsLogic({ tabId }), ['allEndpoints', 'allEndpointsLoading']],
    })),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setEndpointFilter: (endpointFilter: string[]) => ({ endpointFilter }),
        setMaterializationType: (materializationType: 'materialized' | 'inline' | null) => ({ materializationType }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setBreakdownBy: (breakdownBy: EndpointsUsageBreakdown | null) => ({ breakdownBy }),
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            } as { dateFrom: string | null; dateTo: string | null },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],
        endpointFilter: [
            [] as string[],
            {
                setEndpointFilter: (_, { endpointFilter }) => endpointFilter,
            },
        ],
        materializationType: [
            null as 'materialized' | 'inline' | null,
            {
                setMaterializationType: (_, { materializationType }) => materializationType,
            },
        ],
        interval: [
            INITIAL_INTERVAL as IntervalType,
            {
                setInterval: (_, { interval }) => interval,
            },
        ],
        breakdownBy: [
            null as EndpointsUsageBreakdown | null,
            {
                setBreakdownBy: (_, { breakdownBy }) => breakdownBy,
            },
        ],
    }),

    selectors({
        endpointNames: [
            (s) => [s.allEndpoints],
            (allEndpoints: EndpointType[]): string[] =>
                allEndpoints
                    .filter((e) => e.last_executed_at)
                    .map((e) => e.name)
                    .sort(),
        ],
        endpointNamesLoading: [(s) => [s.allEndpointsLoading], (loading: boolean): boolean => loading],
        dateRange: [
            (s) => [s.dateFilter],
            (dateFilter): { date_from: string | null; date_to: string | null } => {
                const dateFromDayjs = dateStringToDayJs(dateFilter.dateFrom)
                const dateToDayjs = dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo) : null

                return {
                    date_from: dateFromDayjs?.format('YYYY-MM-DD') ?? dayjs().subtract(7, 'day').format('YYYY-MM-DD'),
                    date_to: dateToDayjs?.format('YYYY-MM-DD') ?? null,
                }
            },
        ],

        overviewQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType],
            (dateRange, endpointFilter, materializationType): EndpointsUsageOverviewQuery => ({
                kind: NodeKind.EndpointsUsageOverviewQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                compareFilter: { compare: true },
            }),
        ],

        requestsTrendsQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType, s.interval, s.breakdownBy],
            (dateRange, endpointFilter, materializationType, interval, breakdownBy): EndpointsUsageTrendsQuery => ({
                kind: NodeKind.EndpointsUsageTrendsQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                metric: 'requests',
                interval,
                breakdownBy: breakdownBy ?? undefined,
            }),
        ],

        bytesReadTrendsQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType, s.interval, s.breakdownBy],
            (dateRange, endpointFilter, materializationType, interval, breakdownBy): EndpointsUsageTrendsQuery => ({
                kind: NodeKind.EndpointsUsageTrendsQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                metric: 'bytes_read',
                interval,
                breakdownBy: breakdownBy ?? undefined,
            }),
        ],

        cpuSecondsTrendsQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType, s.interval, s.breakdownBy],
            (dateRange, endpointFilter, materializationType, interval, breakdownBy): EndpointsUsageTrendsQuery => ({
                kind: NodeKind.EndpointsUsageTrendsQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                metric: 'cpu_seconds',
                interval,
                breakdownBy: breakdownBy ?? undefined,
            }),
        ],

        queryDurationTrendsQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType, s.interval, s.breakdownBy],
            (dateRange, endpointFilter, materializationType, interval, breakdownBy): EndpointsUsageTrendsQuery => ({
                kind: NodeKind.EndpointsUsageTrendsQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                metric: 'query_duration',
                interval,
                breakdownBy: breakdownBy ?? undefined,
            }),
        ],

        errorRateTrendsQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType, s.interval, s.breakdownBy],
            (dateRange, endpointFilter, materializationType, interval, breakdownBy): EndpointsUsageTrendsQuery => ({
                kind: NodeKind.EndpointsUsageTrendsQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                metric: 'error_rate',
                interval,
                breakdownBy: breakdownBy ?? undefined,
            }),
        ],

        endpointTableQuery: [
            (s) => [s.dateRange, s.endpointFilter, s.materializationType],
            (dateRange, endpointFilter, materializationType): EndpointsUsageTableQuery => ({
                kind: NodeKind.EndpointsUsageTableQuery,
                dateRange,
                endpointNames: endpointFilter.length > 0 ? endpointFilter : undefined,
                materializationType,
                breakdownBy: EndpointsUsageBreakdown.Endpoint,
                orderBy: ['requests', 'DESC'],
                limit: 100,
            }),
        ],
    }),

    tabAwareActionToUrl(({ values }) => {
        const actionToUrl = ({
            dateFilter = values.dateFilter,
            endpointFilter = values.endpointFilter,
            materializationType = values.materializationType,
            interval = values.interval,
            breakdownBy = values.breakdownBy,
        }): [string, Record<string, any> | undefined, string | undefined] | undefined => {
            const { dateFrom, dateTo } = dateFilter
            const searchParams = { ...router.values.searchParams }

            if (dateFrom !== INITIAL_DATE_FROM) {
                searchParams.dateFrom = dateFrom
            } else {
                delete searchParams.dateFrom
            }

            if (dateTo !== INITIAL_DATE_TO) {
                searchParams.dateTo = dateTo
            } else {
                delete searchParams.dateTo
            }

            if (endpointFilter.length > 0) {
                searchParams.endpointFilter = endpointFilter.join(',')
            } else {
                delete searchParams.endpointFilter
            }

            if (materializationType !== null) {
                searchParams.materializationType = materializationType
            } else {
                delete searchParams.materializationType
            }

            if (interval !== INITIAL_INTERVAL) {
                searchParams.interval = interval
            } else {
                delete searchParams.interval
            }

            if (breakdownBy !== null) {
                searchParams.breakdownBy = breakdownBy
            } else {
                delete searchParams.breakdownBy
            }

            return [router.values.location.pathname, searchParams, router.values.location.hash]
        }

        return {
            setDates: actionToUrl,
            setEndpointFilter: actionToUrl,
            setMaterializationType: actionToUrl,
            setInterval: actionToUrl,
            setBreakdownBy: actionToUrl,
        }
    }),

    tabAwareUrlToAction(({ actions }) => ({
        [urls.endpointsUsage()]: (_, searchParams) => {
            const { dateFrom, dateTo, endpointFilter, materializationType, interval, breakdownBy } = searchParams
            actions.setDates(dateFrom ?? INITIAL_DATE_FROM, dateTo ?? INITIAL_DATE_TO)
            actions.setEndpointFilter(endpointFilter ? endpointFilter.split(',') : [])
            actions.setMaterializationType(materializationType ?? null)
            actions.setInterval(interval ?? INITIAL_INTERVAL)
            actions.setBreakdownBy(breakdownBy ?? null)
        },
    })),
])
