import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { isDefinitionStale } from 'lib/utils/definitions'
import { sceneLogic } from 'scenes/sceneLogic'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import {
    AnyPropertyFilter,
    BaseMathType,
    ChartDisplayType,
    EventDefinitionType,
    HogQLMathType,
    PropertyFilterType,
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
    selectors({
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
                        properties: propertyFilters.concat({
                            type: PropertyFilterType.HogQL,
                            key: 'distinct_id != properties.$ai_trace_id',
                        }),
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
                        properties: propertyFilters.concat({
                            type: PropertyFilterType.HogQL,
                            key: 'distinct_id != properties.$ai_trace_id',
                        }),
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
                            decimalPlaces: 2,
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
                        `<strong><a href=f'/llm-observability/traces/{properties.$ai_trace_id}?event={uuid}'>
                            {f'{left(toString(uuid), 4)}...{right(toString(uuid), 4)}'}
                        </a></strong> -- ID`,
                        `<a href=f'/llm-observability/traces/{properties.$ai_trace_id}'>
                            {f'{left(properties.$ai_trace_id, 4)}...{right(properties.$ai_trace_id, 4)}'}
                        </a> -- Trace ID`,
                        'person',
                        "f'{properties.$ai_model}' -- Model",
                        "f'{round(properties.$ai_latency, 2)} s' -- Latency",
                        "f'{properties.$ai_input_tokens} → {properties.$ai_output_tokens} (∑ {properties.$ai_input_tokens + properties.$ai_output_tokens})' -- Token usage",
                        "f'${round(toFloat(properties.$ai_total_cost_usd), 6)}' -- Total cost",
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
                showActions: false,
            }),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadAIEventDefinition()
    }),
])
