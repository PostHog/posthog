import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TraceQuery } from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb, InsightLogicProps } from '~/types'

import type { llmAnalyticsTraceLogicType } from './llmAnalyticsTraceLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

export enum DisplayOption {
    ExpandAll = 'expand_all',
    CollapseExceptOutputAndLastInput = 'collapse_except_output_and_last_input',
    TextView = 'text_view',
}

export enum TraceViewMode {
    Conversation = 'conversation',
    Raw = 'raw',
    Summary = 'summary',
    Evals = 'evals',
    Clusters = 'clusters',
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

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
        setEventId: (eventId: string | null) => ({ eventId }),
        setLineNumber: (lineNumber: number | null) => ({ lineNumber }),
        setInitialTab: (tab: string | null) => ({ tab }),
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
        handleTextViewFallback: true,
        copyLinePermalink: (lineNumber: number) => ({ lineNumber }),
        toggleEventTypeExpanded: (eventType: string) => ({ eventType }),
        loadCommentCount: true,
        setViewMode: (viewMode: TraceViewMode) => ({ viewMode }),
    }),

    reducers({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
        lineNumber: [null as number | null, { setLineNumber: (_, { lineNumber }) => lineNumber }],
        initialTab: [null as string | null, { setInitialTab: (_, { tab }) => tab }],
        viewMode: [
            TraceViewMode.Conversation as TraceViewMode,
            {
                setViewMode: (_, { viewMode }) => viewMode,
                setInitialTab: (_, { tab }) => {
                    if (tab === 'summary') {
                        return TraceViewMode.Summary
                    }
                    if (tab === 'raw') {
                        return TraceViewMode.Raw
                    }
                    if (tab === 'evals') {
                        return TraceViewMode.Evals
                    }
                    if (tab === 'clusters') {
                        return TraceViewMode.Clusters
                    }
                    return TraceViewMode.Conversation
                },
            },
        ],
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
                handleTextViewFallback: () => DisplayOption.ExpandAll,
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

    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    if (
                        !values.traceId ||
                        !(
                            values.featureFlags?.[FEATURE_FLAGS.LLM_ANALYTICS_DISCUSSIONS] ||
                            values.featureFlags?.[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
                        )
                    ) {
                        return 0
                    }

                    await breakpoint(100)
                    const response = await api.comments.getCount({
                        scope: ActivityScope.LLM_TRACE,
                        item_id: values.traceId,
                        exclude_emoji_reactions: true,
                    })

                    breakpoint()

                    return response
                },
            },
        ],
    })),

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
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.traceId, s.featureFlags],
            (traceId, featureFlags): SidePanelSceneContext => {
                // Discussions are always at the trace level, accessible from anywhere in the trace
                return {
                    activity_scope: ActivityScope.LLM_TRACE,
                    activity_item_id: traceId || '',
                    discussions_disabled: !(
                        featureFlags?.[FEATURE_FLAGS.LLM_ANALYTICS_DISCUSSIONS] ||
                        featureFlags?.[FEATURE_FLAGS.LLM_ANALYTICS_EARLY_ADOPTERS]
                    ),
                    activity_item_context: { trace_id: traceId || '' },
                }
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
        copyLinePermalink: ({ lineNumber }) => {
            // Copy permalink to clipboard with line number in URL
            const url = new URL(window.location.href)
            url.searchParams.set('line', lineNumber.toString())
            copyToClipboard(url.toString(), 'permalink')
        },
    })),

    subscriptions(({ actions }) => ({
        traceId: (traceId: string) => {
            if (traceId) {
                actions.loadCommentCount()

                // Mark both tasks as completed - viewing a trace implies AI events were sent
                globalSetupLogic
                    .findMounted()
                    ?.actions.markTaskAsCompleted([SetupTaskId.IngestFirstLlmEvent, SetupTaskId.ViewFirstTrace])
            }
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.llmAnalyticsTrace(':id')]: ({ id }, { event, timestamp, exception_ts, search, line, tab }) => {
            actions.setTraceId(id ?? '')
            actions.setEventId(event || null)
            actions.setLineNumber(line ? parseInt(line, 10) : null)
            actions.setInitialTab(tab || null)
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

    actionToUrl(({ values }) => {
        const buildUrl = (): string | undefined => {
            if (!values.traceId) {
                return undefined
            }
            const params: Record<string, string> = {}
            if (values.eventId) {
                params.event = values.eventId
            }
            if (values.dateRange) {
                if (values.dateRange.dateFrom && !values.dateRange.dateTo) {
                    params.timestamp = values.dateRange.dateFrom
                } else if (values.dateRange.dateFrom && values.dateRange.dateTo) {
                    params.exception_ts = dayjs(values.dateRange.dateFrom)
                        .add(EXCEPTION_LOOKUP_WINDOW_MINUTES, 'minutes')
                        .toISOString()
                }
            }
            if (values.searchQuery) {
                params.search = values.searchQuery
            }
            if (values.lineNumber) {
                params.line = values.lineNumber.toString()
            }
            // Always include tab parameter
            params.tab = values.viewMode
            return urls.llmAnalyticsTrace(values.traceId, params)
        }

        return {
            setViewMode: buildUrl,
        }
    }),
])
