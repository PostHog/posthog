import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, DataTableNode, NodeKind, TracesQuery } from '~/queries/schema/schema-general'
import { Breadcrumb, InsightLogicProps } from '~/types'

import type { llmObservabilityTraceLogicType } from './llmObservabilityTraceLogicType'

export enum DisplayOption {
    ExpandAll = 'expand_all',
    CollapseExceptOutputAndLastInput = 'collapse_except_output_and_last_input',
}

export interface LLMObservabilityTraceDataNodeLogicParams {
    traceId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

export function getDataNodeLogicProps({
    traceId,
    query,
    cachedResults,
}: LLMObservabilityTraceDataNodeLogicParams): DataNodeLogicProps {
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

export const llmObservabilityTraceLogic = kea<llmObservabilityTraceLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityTraceLogic']),

    actions({
        setTraceId: (traceId: string) => ({ traceId }),
        setEventId: (eventId: string | null) => ({ eventId }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
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
        showDisplayOptionsModal: true,
        hideDisplayOptionsModal: true,
        setDisplayOption: (displayOption: DisplayOption) => ({ displayOption }),
    }),

    reducers({
        traceId: ['' as string, { setTraceId: (_, { traceId }) => traceId }],
        eventId: [null as string | null, { setEventId: (_, { eventId }) => eventId }],
        dateFrom: [null as string | null, { setDateFrom: (_, { dateFrom }) => dateFrom }],
        searchQuery: ['' as string, { setSearchQuery: (_, { searchQuery }) => String(searchQuery || '') }],
        isRenderingMarkdown: [
            true as boolean,
            {
                setIsRenderingMarkdown: (_, { isRenderingMarkdown }) => isRenderingMarkdown,
                toggleMarkdownRendering: (state) => !state,
            },
        ],
        isRenderingXml: [
            false as boolean,
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
        displayOptionsModalVisible: [
            false as boolean,
            {
                showDisplayOptionsModal: () => true,
                hideDisplayOptionsModal: () => false,
            },
        ],
        displayOption: [
            DisplayOption.CollapseExceptOutputAndLastInput as DisplayOption,
            {
                setDisplayOption: (_, { displayOption }) => displayOption,
            },
        ],
    }),

    selectors({
        // Direct access to message states (no computation needed!)
        inputMessageShowStates: [(s) => [s.messageShowStates], (messageStates) => messageStates.input],
        outputMessageShowStates: [(s) => [s.messageShowStates], (messageStates) => messageStates.output],
        query: [
            (s) => [s.traceId, s.dateFrom],
            (traceId, dateFrom): DataTableNode => {
                const tracesQuery: TracesQuery = {
                    kind: NodeKind.TracesQuery,
                    traceId,
                    dateRange: dateFrom
                        ? // dateFrom is a minimum timestamp of an event for a trace.
                          {
                              date_from: dateFrom,
                              date_to: dayjs(dateFrom).add(10, 'minutes').toISOString(),
                          }
                        : // By default will look for traces from the beginning.
                          {
                              date_from: dayjs.utc(new Date(2025, 0, 10)).toISOString(),
                          },
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: tracesQuery,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.traceId],
            (traceId): Breadcrumb[] => {
                return [
                    {
                        key: 'LLMObservability',
                        name: 'LLM observability',
                        path: urls.llmObservabilityDashboard(),
                    },
                    {
                        key: 'LLMObservabilityTraces',
                        name: 'Traces',
                        path: urls.llmObservabilityTraces(),
                    },
                    {
                        key: ['LLMObservabilityTrace', traceId || ''],
                        name: traceId,
                    },
                ]
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        setIsRenderingMarkdown: ({ isRenderingMarkdown }) => {
            localStorage.setItem('llm-observability-markdown-rendering', JSON.stringify(isRenderingMarkdown))
        },
        toggleMarkdownRendering: () => {
            localStorage.setItem('llm-observability-markdown-rendering', JSON.stringify(values.isRenderingMarkdown))
        },
        setIsRenderingXml: ({ isRenderingXml }) => {
            localStorage.setItem('llm-observability-xml-rendering', JSON.stringify(isRenderingXml))
        },
        toggleXmlRendering: () => {
            localStorage.setItem('llm-observability-xml-rendering', JSON.stringify(values.isRenderingXml))
        },
        setDisplayOption: ({ displayOption }) => {
            localStorage.setItem('llm-observability-display-option', JSON.stringify(displayOption))
        },
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
                const { traceId, eventId, dateFrom } = values
                if (traceId) {
                    const params: any = {}
                    if (eventId) {
                        params.event = eventId
                    }
                    if (dateFrom) {
                        params.timestamp = dateFrom
                    }
                    if (searchQuery) {
                        params.search = searchQuery
                    }

                    // Use router to update URL
                    router.actions.replace(urls.llmObservabilityTrace(traceId, params))
                }
            }
        },
    })),

    afterMount(({ actions }) => {
        const savedMarkdownState = localStorage.getItem('llm-observability-markdown-rendering')
        if (savedMarkdownState !== null) {
            try {
                const isRenderingMarkdown = JSON.parse(savedMarkdownState)
                actions.setIsRenderingMarkdown(isRenderingMarkdown)
            } catch {
                // If parsing fails, keep the default value
            }
        }

        const savedXmlState = localStorage.getItem('llm-observability-xml-rendering')
        if (savedXmlState !== null) {
            try {
                const isRenderingXml = JSON.parse(savedXmlState)
                actions.setIsRenderingXml(isRenderingXml)
            } catch {
                // If parsing fails, keep the default value
            }
        }

        const savedDisplayOption = localStorage.getItem('llm-observability-display-option')
        if (savedDisplayOption !== null) {
            try {
                const displayOption = JSON.parse(savedDisplayOption)
                actions.setDisplayOption(displayOption)
            } catch {
                // If parsing fails, keep the default value
            }
        }
    }),

    urlToAction(({ actions }) => ({
        [urls.llmObservabilityTrace(':id')]: ({ id }, { event, timestamp, search }) => {
            actions.setTraceId(id ?? '')
            actions.setEventId(event || null)
            actions.setDateFrom(timestamp || null)
            // Set search from URL param if provided, otherwise clear it
            actions.setSearchQuery(search || '')
        },
    })),
])
