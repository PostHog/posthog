import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils'
import { isDefinitionStale } from 'lib/utils/definitions'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { isAnyPropertyFilters } from '~/queries/schema-guards'
import { QueryContext } from '~/queries/types'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    EventDefinitionType,
    HogQLMathType,
    PropertyMathType,
} from '~/types'

import type { llmObservabilityLogicType } from './llmObservabilityLogicType'

export const LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID = 'llm-observability-data'

const INITIAL_DATE_FROM = '-7d' as string | null
const INITIAL_DATE_TO = null as string | null

export interface QueryTile {
    title: string
    description?: string
    query: TrendsQuery
    context?: QueryContext
    layout?: {
        className?: string
    }
}

export const llmObservabilityLogic = kea<llmObservabilityLogicType>([
    path(['products', 'llm_observability', 'frontend', 'llmObservabilityLogic']),
    connect({ values: [sceneLogic, ['sceneKey']] }),
    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setPropertyFilters: (propertyFilters: AnyPropertyFilter[]) => ({ propertyFilters }),
    }),
    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],
        shouldFilterTestAccounts: [
            false,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],
        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                setPropertyFilters: (_, { propertyFilters }) => propertyFilters,
            },
        ],
    }),

    loaders({
        hasSentAiGenerationEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean> => {
                const aiGenerationDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$ai_generation',
                })

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const definition = aiGenerationDefinition.results.find((r) => r.name === '$ai_generation')
                if (definition && !isDefinitionStale(definition)) {
                    return true
                }
                return false
            },
        },
    }),
    selectors(() => ({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey) => {
                if (sceneKey === 'llmObservabilityGenerations') {
                    return 'generations'
                } else if (sceneKey === 'llmObservabilityTraces') {
                    return 'traces'
                }
                return 'dashboard'
            },
        ],
        tiles: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts, s.propertyFilters],
            (dateFilter, shouldFilterTestAccounts, propertyFilters): QueryTile[] => [
                {
                    title: 'Traces',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: HogQLMathType.HogQL,
                                math_hogql: 'COUNT(DISTINCT properties.$ai_trace_id)',
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                    context: {
                        groupTypeLabel: 'traces',
                        onDataPointClick: (series) => {
                            if (typeof series.day === 'string') {
                                // NOTE: This assumes the chart is day-by-day
                                const dayStart = dayjs(series.day).startOf('day')
                                router.actions.push(urls.llmObservabilityTraces(), {
                                    date_from: dayStart.format('YYYY-MM-DD[T]HH:mm:ss'),
                                    date_to: dayStart
                                        .add(1, 'day')
                                        .subtract(1, 'second')
                                        .format('YYYY-MM-DD[T]HH:mm:ss'),
                                })
                            }
                        },
                    },
                },
                {
                    title: 'Generative AI users',
                    description: 'To count users, set `distinct_id` in LLM tracking.',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Total cost (USD)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 4,
                            display: ChartDisplayType.BoldNumber,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Cost per user (USD)',
                    description: "Average cost for each generative AI user active in the data point's period.",
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        trendsFilter: {
                            formula: 'A / B',
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Cost by model (USD)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        breakdownFilter: {
                            breakdown_type: 'event',
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                            display: ChartDisplayType.ActionsBarValue,
                            showValuesOnSeries: true,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Generation calls',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Generation latency by model (median)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                math: PropertyMathType.Median,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_latency',
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPostfix: ' s',
                            decimalPlaces: 3,
                            yAxisScaleType: 'log10',
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Generations by HTTP status',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                name: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_http_status',
                        },
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBarValue,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        properties: propertyFilters,
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
            ],
        ],
        tracesQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                groupsModel.selectors.groupsTaxonomicTypes,
            ],
            (dateFilter, shouldFilterTestAccounts, propertyFilters, groupsTaxonomicTypes): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.TracesQuery,
                    dateRange: {
                        date_from: dateFilter.dateFrom || undefined,
                        date_to: dateFilter.dateTo || undefined,
                    },
                    filterTestAccounts: shouldFilterTestAccounts ?? false,
                    properties: propertyFilters,
                },
                columns: ['id', 'person', 'totalLatency', 'usage', 'totalCost', 'timestamp'],
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showTestAccountFilters: true,
                showExport: true,
                showOpenEditorButton: false,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
            }),
        ],
        generationsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                groupsModel.selectors.groupsTaxonomicTypes,
            ],
            (dateFilter, shouldFilterTestAccounts, propertyFilters, groupsTaxonomicTypes): DataTableNode => ({
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: [
                        '*',
                        'person',
                        // The f-string wrapping below seems pointless, but it actually disables special rendering
                        // of the property keys, which would otherwise show property names overly verbose here
                        "f'{properties.$ai_trace_id}' -- Trace ID",
                        "f'{properties.$ai_model}' -- Model",
                        "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Total cost",
                        "f'{properties.$ai_input_tokens} → {properties.$ai_output_tokens} (∑ {properties.$ai_input_tokens + properties.$ai_output_tokens})' -- Token usage",
                        "f'{properties.$ai_latency} s' -- Latency",
                        'timestamp',
                    ],
                    orderBy: ['timestamp DESC'],
                    after: dateFilter.dateFrom || undefined,
                    before: dateFilter.dateTo || undefined,
                    filterTestAccounts: shouldFilterTestAccounts,
                    event: '$ai_generation',
                    properties: propertyFilters,
                },
                showDateRange: true,
                showReload: true,
                showSearch: true,
                showTestAccountFilters: true,
                showColumnConfigurator: true,
                showPropertyFilter: [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
                showExport: true,
            }),
        ],
    })),

    urlToAction(({ actions, values }) => {
        function applySearchParams({ filters, date_from, date_to, filter_test_accounts }: Record<string, any>): void {
            // Reusing logic and naming from webAnalyticsLogic
            const parsedFilters = isAnyPropertyFilters(filters) ? filters : []
            if (!objectsEqual(parsedFilters, values.propertyFilters)) {
                actions.setPropertyFilters(parsedFilters)
            }
            if (
                (date_from || INITIAL_DATE_FROM) !== values.dateFilter.dateFrom ||
                (date_to || INITIAL_DATE_TO) !== values.dateFilter.dateTo
            ) {
                actions.setDates(date_from || null, date_to || null)
            }
            const filterTestAccountsValue = [true, 'true', 1, '1'].includes(filter_test_accounts)
            if (filterTestAccountsValue !== values.shouldFilterTestAccounts) {
                actions.setShouldFilterTestAccounts(filterTestAccountsValue)
            }
        }

        return {
            [urls.llmObservabilityDashboard()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmObservabilityGenerations()]: (_, searchParams) => applySearchParams(searchParams),
            [urls.llmObservabilityTraces()]: (_, searchParams) => applySearchParams(searchParams),
        }
    }),

    actionToUrl(() => ({
        setPropertyFilters: ({ propertyFilters }) => [
            router.values.currentLocation.pathname,
            {
                ...router.values.currentLocation.searchParams,
                filters: propertyFilters,
            },
        ],
        setDates: ({ dateFrom, dateTo }) => [
            router.values.currentLocation.pathname,
            {
                ...router.values.currentLocation.searchParams,
                date_from: dateFrom || undefined,
                date_to: dateTo || undefined,
            },
        ],
        setShouldFilterTestAccounts: ({ shouldFilterTestAccounts }) => [
            router.values.currentLocation.pathname,
            {
                ...router.values.currentLocation.searchParams,
                filter_test_accounts: shouldFilterTestAccounts ? 'true' : undefined,
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadAIEventDefinition()
    }),
])
