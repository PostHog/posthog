import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { urls } from 'scenes/urls'

import { DateRange, InsightVizNode, NodeKind, ProductKey, TrendsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, BaseMathType, ChartDisplayType, IntervalType } from '~/types'

export interface InsightQueryFilters {
    properties: AnyPropertyFilter[]
    filterTestAccounts: boolean
}

const MAX_HOURS_FOR_HOURLY_INTERVAL = 25

export function getInterval(dateFrom: string | null | undefined, dateTo: string | null | undefined): IntervalType {
    const from = dateStringToDayJs(dateFrom ?? null)
    const to = dateStringToDayJs(dateTo ?? null) ?? dayjs()
    if (from && to.diff(from, 'hour') < MAX_HOURS_FOR_HOURLY_INTERVAL) {
        return 'hour'
    }
    return 'day'
}

export function buildExceptionVolumeQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
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
            dateRange,
            trendsFilter: { display: ChartDisplayType.ActionsBar },
            filterTestAccounts,
            properties,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
    }
}

export function buildAffectedUsersQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
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
            dateRange,
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            filterTestAccounts,
            properties,
            tags: { productKey: ProductKey.ERROR_TRACKING },
        },
        showHeader: false,
        showTable: false,
    }
}

export function buildCrashFreeSessionsQuery(
    dateRange: DateRange,
    { properties, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
    const interval = getInterval(dateRange.date_from, dateRange.date_to)
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
            dateRange,
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: '(A - B) / A * 100', custom_name: 'Crash-free sessions %' }],
                aggregationAxisPostfix: '%',
            },
            filterTestAccounts,
            properties,
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
