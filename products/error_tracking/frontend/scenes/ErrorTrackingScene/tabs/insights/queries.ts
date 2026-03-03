import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyGroupFilter, UniversalFiltersGroup } from '~/types'

export interface InsightQueryFilters {
    filterGroup: UniversalFiltersGroup
    filterTestAccounts: boolean
}

export function formatQueryForInsightEditor(query: InsightVizNode<TrendsQuery>): InsightVizNode<TrendsQuery> {
    return {
        ...query,
        source: {
            ...query.source,
            dateRange: {
                date_from: 'wStart',
                date_to: null,
            },
        },
        // Open in regular insight mode with full controls visible.
        full: true,
        showHeader: undefined,
        showTable: undefined,
        showFilters: undefined,
        embedded: undefined,
    }
}

export function buildExceptionVolumeQuery(
    dateFrom: string,
    dateTo: string | null,
    { filterGroup, filterTestAccounts }: InsightQueryFilters
): InsightVizNode<TrendsQuery> {
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
            interval: 'day',
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: { display: ChartDisplayType.ActionsBar },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
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
            interval: 'day',
            dateRange: { date_from: dateFrom, date_to: dateTo },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
                formulaNodes: [{ formula: '(A - B) / A * 100', custom_name: 'Crash-free sessions %' }],
                aggregationAxisPostfix: '%',
            },
            filterTestAccounts,
            properties: filterGroup as PropertyGroupFilter,
        },
        showHeader: false,
        showTable: false,
    }
}

export function insightNewUrl(query: InsightVizNode<TrendsQuery>): string {
    return urls.insightNew({ query: formatQueryForInsightEditor(query) })
}
