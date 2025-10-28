import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TraceQuery } from '~/queries/schema/schema-general'
import { Breadcrumb, InsightLogicProps } from '~/types'

import type { llmAnalyticsTraceLogicType } from './llmAnalyticsTraceLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

export enum DisplayOption {
    ExpandAll = 'expand_all',
    CollapseExceptOutputAndLastInput = 'collapse_except_output_and_last_input',
    TextView = 'text_view',
}

export interface LLMAnalyticsTraceDataNodeLogicParams {
    traceId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

const EXCEPTION_LOOKUP_WINDOW_MINUTES = 20

export function getDataNodeLogicProps({
    traceId,
    query,
    cachedResults,
}: LLMAnalyticsTraceDataNodeLogicParams): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Trace.${traceId}`,
        dataNodeCollectionId: traceId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: traceId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export const llmAnalyticsTraceLogic = kea<llmAnalyticsTraceLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsTraceLogic']),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
        setEventId: (eventId: string | null) => ({ eventId }),
        setDateRange: (dateFrom: string | null, dateTo?: string | null) => ({ dateFrom, dateTo }),
        setIsRenderingMarkdown: (isRenderingMarkdown: boolean) => ({ isRenderingMarkdown }),
        toggleMarkdownRendering: true,
        setIsRenderingXml: (isRenderingXml: boolean) => ({ isRenderingXml }),
        toggleXmlRendering: true,
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        initializeMessageStates: (inputCount: number, outputCount: number) => ({ inputCount, outputCount }),
        toggleMessage: (type: 'input' | 'output', index: number) => ({ type, index }),
        showAllMessages: (type: 'input' | 'output') => ({ type }),
        hideAllMessages: (type: 'input' | 'output') => ({ type }),
        applySearchResults: (inputMatches: boolean[], outputMatches: boolean[]) => ({ inputMatches, outputMatches }),
        setDisplayOption: (displayOption: DisplayOption) => ({ displayOption }),
        toggleEventTypeExpanded: (eventType: string) => ({ eventType }),
    }),

    reducers({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
        dateRange: [
            null as { dateFrom: string | null; dateTo: string | null } | null,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({
                    dateFrom: dateFrom ?? null,
                    dateTo: dateTo ?? null,
                }),
            },
        ],
        searchQuery: ['' as string, { setSearchQuery: (_, { searchQuery }) => String(searchQuery || '') }],
        isRenderingMarkdown: [
            true as boolean,
            persistConfig,
            {
                setIsRenderingMarkdown: (_, { isRenderingMarkdown }) => isRenderingMarkdown,
                toggleMarkdownRendering: (state) => !state,
            },
        ],
        isRenderingXml: [
            false as boolean,
            persistConfig,
            {
                setIsRenderingXml: (_, { isRenderingXml }) => isRenderingXml,
                toggleXmlRendering: (state) => !state,
            },
        ],
        // Single source of truth for message visibility
        messageShowStates: [
            { input: [] as boolean[], output: [] as boolean[] },
            {
                initializeMessageStates: (_, { inputCount, outputCount }) => {
                    // Will be initialized based on display option in listener
                    const inputStates = new Array(inputCount).fill(false)
                    const outputStates = new Array(outputCount).fill(true)
                    return { input: inputStates, output: outputStates }
                },
                toggleMessage: (state, { type, index }) => {
                    const newStates = { ...state }
                    newStates[type] = [...state[type]]
                    newStates[type][index] = !newStates[type][index]
                    return newStates
                },
                showAllMessages: (state, { type }) => {
                    const newStates = { ...state }
                    newStates[type] = state[type].map(() => true)
                    return newStates
                },
                hideAllMessages: (state, { type }) => {
                    const newStates = { ...state }
                    newStates[type] = state[type].map(() => false)
                    return newStates
                },
                applySearchResults: (_, { inputMatches, outputMatches }) => {
                    // When search results come in, expand messages with matches
                    return {
                        input: inputMatches,
                        output: outputMatches,
                    }
                },
                setSearchQuery: (state) => {
                    // Keep current state when search query changes (will be updated by applySearchResults)
                    return state
                },
            },
        ],
        displayOption: [
            DisplayOption.CollapseExceptOutputAndLastInput as DisplayOption,
            persistConfig,
            {
                setDisplayOption: (_, { displayOption }) => displayOption,
            },
        ],
        eventTypeExpandedMap: [
            {} as Record<string, boolean>,
            persistConfig,
            {
                toggleEventTypeExpanded: (state, { eventType }) => ({
                    ...state,
                    [eventType]: !(state[eventType] ?? true),
                }),
            },
        ],
    }),

    selectors({
        inputMessageShowStates: [(s) => [s.messageShowStates], (messageStates) => messageStates.input],
        outputMessageShowStates: [(s) => [s.messageShowStates], (messageStates) => messageStates.output],
        query: [
            (s) => [s.traceId, s.dateRange],
            (traceId, dateRange): DataTableNode => {
                const traceQuery: TraceQuery = {
                    kind: NodeKind.TraceQuery,
                    traceId,
                    dateRange: dateRange?.dateFrom
                        ? // dateFrom is a minimum timestamp of an event for a trace.
                          {
                              date_from: dateRange.dateFrom,
                              date_to: dateRange?.dateTo || dayjs(dateRange.dateFrom).add(10, 'minutes').toISOString(),
                          }
                        : // By default will look for traces from the beginning.
                          {
                              date_from: dayjs.utc(new Date(2025, 0, 10)).toISOString(),
                          },
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: traceQuery,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.traceId],
            (traceId): Breadcrumb[] => {
                return [
                    {
                        key: 'LLMAnalytics',
                        name: 'LLM analytics',
                        path: urls.llmAnalyticsDashboard(),
                        iconType: 'llm_analytics',
                    },
                    {
                        key: 'LLMAnalyticsTraces',
                        name: 'Traces',
                        path: urls.llmAnalyticsTraces(),
                        iconType: 'llm_analytics',
                    },
                    {
                        key: ['LLMAnalyticsTrace', traceId || ''],
                        name: traceId,
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
        eventTypeExpanded: [
            (s) => [s.eventTypeExpandedMap],
            (eventTypeExpandedMap) =>
                (eventType: string): boolean => {
                    return eventTypeExpandedMap[eventType] ?? true
                },
        ],
    }),

    listeners(({ actions, values }) => ({
        initializeMessageStates: ({ inputCount, outputCount }) => {
            // Apply display option when initializing
            const displayOption = values.displayOption
            const inputStates = new Array(inputCount).fill(false).map((_, i) => {
                if (displayOption === DisplayOption.ExpandAll) {
                    return true
                }
                // For collapse except output and last input, only show last input
                return i === inputCount - 1
            })
            const outputStates = new Array(outputCount).fill(true)

            // Update the states directly
            actions.applySearchResults(inputStates, outputStates)
        },
        setSearchQuery: ({ searchQuery }) => {
            // Only update URL if the search query actually changed
            // This prevents infinite loop when setSearchQuery is called from urlToAction
            const currentUrl = window.location.search
            const urlParams = new URLSearchParams(currentUrl)
            const currentSearchInUrl = urlParams.get('search') || ''

            if (searchQuery !== currentSearchInUrl) {
                // Update the URL with the search query
                const { traceId, eventId, dateRange } = values
                if (traceId) {
                    const params: any = {}
                    if (eventId) {
                        params.event = eventId
                    }
                    if (dateRange) {
                        if (dateRange.dateFrom && !dateRange.dateTo) {
                            params.timestamp = dateRange.dateFrom
                        } else if (dateRange.dateFrom && dateRange.dateTo) {
                            params.exception_ts = dayjs(dateRange.dateFrom)
                                .add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes')
                                .toISOString()
                        }
                    }
                    if (searchQuery) {
                        params.search = searchQuery
                    }

                    // Use router to update URL
                    router.actions.replace(urls.llmAnalyticsTrace(traceId, params))
                }
            }
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.llmAnalyticsTrace(':id')]: ({ id }, { event, timestamp, exception_ts, search }) => {
            actions.setTraceId(id ?? '')
            actions.setEventId(event || null)
            if (timestamp) {
                actions.setDateRange(timestamp || null)
            } else if (exception_ts) {
                // Increase the lookup window to 20 minutes before and after the exception timestamp, which gives in total 60 minutes.
                const parsedDate = dayjs(exception_ts)
                actions.setDateRange(
                    parsedDate.subtract(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes').toISOString(),
                    parsedDate.add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes').toISOString()
                )
            }
            // Set search from URL param if provided, otherwise clear it
            actions.setSearchQuery(search || '')
        },
    })),
])
