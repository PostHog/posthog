import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, IntervalType, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

export interface InsightQueryFilters {
    filterGroup: UniversalFiltersGroup
    filterTestAccounts: boolean
}

const MAX_HOURS_FOR_HOURLY_INTERVAL = 25

export function getInterval(dateFrom: string | null, dateTo: string | null): IntervalType {
    const from = dateStringToDayJs(dateFrom)
    const to = dateStringToDayJs(dateTo) ?? dayjs()
    if (from && to.diff(from, 'hour') < MAX_HOURS_FOR_HOURLY_INTERVAL) {
        return 'hour'
    }
    return 'day'
}

export function buildExceptionVolumeQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateFrom, dateTo)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Exceptions',
                },
            ],
            interval,
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.ActionsBar },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
    }
}

export function buildAffectedUsersQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateFrom, dateTo)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Affected users',
                    math: BaseMathType.UniqueUsers,
                },
            ],
            interval,
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
    }
}

export function buildCrashFreeSessionsQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateFrom, dateTo)
    return {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: null,
                    custom_name: 'Total sessions',
                    math: BaseMathType.UniqueSessions,
                },
                {
                    kind: NodeKind.EventsNode,
                    event: '$exception',
                    custom_name: 'Sessions with crash',
                    math: BaseMathType.UniqueSessions,
                },
            ],
            interval,
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: '(A - B) / A * 100', custom_name: 'Crash-free sessions %' }],
                aggregationAxisPostfix: '%',
            },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
    }
}

export function insightNewUrl(query: InsightVizNode<TrendsQuery>): string {
    const editorQuery: InsightVizNode<TrendsQuery> = {
        ...query,
        full: true,
        showHeader: undefined,
        showTable: undefined,
        showFilters: undefined,
        embedded: undefined,
    }
    return urls.insightNew({ query: editorQuery })
}
