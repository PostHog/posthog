import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import {
    EnrichedTraceTreeNode,
    TraceTreeNode,
    getEffectiveEventId,
    getInitialFocusEventId,
} from './llmAnalyticsTraceDataLogic'
import { DisplayOption, TraceViewMode } from './llmAnalyticsTraceLogic'
import { parseTraceExportJson, validateTraceExport } from './traceImportUtils'
import { isLLMEvent } from './utils'

export interface ParsedTraceData {
    trace: LLMTrace
    enrichedTree: EnrichedTraceTreeNode[]
}

export const llmAnalyticsTracePreviewLogic = kea([
    path(['scenes', 'llm-analytics', 'llmAnalyticsTracePreviewLogic']),

    actions({
        setRawJson: (json: string) => ({ json }),
        parseAndLoadTrace: true,
        setParsedTraceData: (data: ParsedTraceData | null) => ({ data }),
        setValidationError: (error: string | null) => ({ error }),
        clearTrace: true,
        setSelectedEventId: (eventId: string | null) => ({ eventId }),
        setViewMode: (viewMode: TraceViewMode) => ({ viewMode }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setDisplayOption: (displayOption: DisplayOption) => ({ displayOption }),
        initializeMessageStates: (inputCount: number, outputCount: number) => ({ inputCount, outputCount }),
        toggleMessage: (type: 'input' | 'output', index: number) => ({ type, index }),
        showAllMessages: (type: 'input' | 'output') => ({ type }),
        hideAllMessages: (type: 'input' | 'output') => ({ type }),
        applySearchResults: (inputMatches: boolean[], outputMatches: boolean[]) => ({
            inputMatches,
            outputMatches,
        }),
        setIsRenderingMarkdown: (isRenderingMarkdown: boolean) => ({ isRenderingMarkdown }),
        toggleMarkdownRendering: true,
        setIsRenderingXml: (isRenderingXml: boolean) => ({ isRenderingXml }),
        toggleXmlRendering: true,
        toggleEventTypeExpanded: (eventType: string) => ({ eventType }),
    }),

    reducers({
        rawJson: [
            '' as string,
            {
                setRawJson: (_, { json }: { json: string }) => json,
                clearTrace: () => '',
            },
        ],
        parsedTraceData: [
            null as ParsedTraceData | null,
            {
                setParsedTraceData: (_, { data }: { data: ParsedTraceData | null }) => data,
                clearTrace: () => null,
            },
        ],
        validationError: [
            null as string | null,
            {
                setRawJson: () => null,
                setValidationError: (_, { error }: { error: string | null }) => error,
                clearTrace: () => null,
            },
        ],
        selectedEventId: [
            null as string | null,
            {
                setSelectedEventId: (_, { eventId }: { eventId: string | null }) => eventId,
                clearTrace: () => null,
            },
        ],
        viewMode: [
            TraceViewMode.Conversation as TraceViewMode,
            {
                setViewMode: (_, { viewMode }: { viewMode: TraceViewMode }) => viewMode,
            },
        ],
        searchQuery: [
            '' as string,
            {
                setSearchQuery: (_, { searchQuery }: { searchQuery: string }) => String(searchQuery || ''),
                clearTrace: () => '',
            },
        ],
        displayOption: [
            DisplayOption.CollapseExceptOutputAndLastInput as DisplayOption,
            {
                setDisplayOption: (_, { displayOption }: { displayOption: DisplayOption }) => displayOption,
            },
        ],
        messageShowStates: [
            { input: [] as boolean[], output: [] as boolean[] },
            {
                initializeMessageStates: (
                    _,
                    { inputCount, outputCount }: { inputCount: number; outputCount: number }
                ) => {
                    const inputStates = new Array(inputCount).fill(false) as boolean[]
                    const outputStates = new Array(outputCount).fill(true) as boolean[]
                    return { input: inputStates, output: outputStates }
                },
                toggleMessage: (
                    state: { input: boolean[]; output: boolean[] },
                    { type, index }: { type: 'input' | 'output'; index: number }
                ) => {
                    const newStates = { ...state }
                    newStates[type] = [...state[type]]
                    newStates[type][index] = !newStates[type][index]
                    return newStates
                },
                showAllMessages: (
                    state: { input: boolean[]; output: boolean[] },
                    { type }: { type: 'input' | 'output' }
                ) => {
                    const newStates = { ...state }
                    newStates[type] = state[type].map(() => true)
                    return newStates
                },
                hideAllMessages: (
                    state: { input: boolean[]; output: boolean[] },
                    { type }: { type: 'input' | 'output' }
                ) => {
                    const newStates = { ...state }
                    newStates[type] = state[type].map(() => false)
                    return newStates
                },
                applySearchResults: (
                    _,
                    { inputMatches, outputMatches }: { inputMatches: boolean[]; outputMatches: boolean[] }
                ) => ({
                    input: inputMatches,
                    output: outputMatches,
                }),
                clearTrace: () => ({ input: [] as boolean[], output: [] as boolean[] }),
            },
        ],
        isRenderingMarkdown: [
            true as boolean,
            {
                setIsRenderingMarkdown: (_, { isRenderingMarkdown }: { isRenderingMarkdown: boolean }) =>
                    isRenderingMarkdown,
                toggleMarkdownRendering: (state: boolean) => !state,
            },
        ],
        isRenderingXml: [
            false as boolean,
            {
                setIsRenderingXml: (_, { isRenderingXml }: { isRenderingXml: boolean }) => isRenderingXml,
                toggleXmlRendering: (state: boolean) => !state,
            },
        ],
        eventTypeExpandedMap: [
            {} as Record<string, boolean>,
            {
                toggleEventTypeExpanded: (state: Record<string, boolean>, { eventType }: { eventType: string }) => ({
                    ...state,
                    [eventType]: !(state[eventType] ?? true),
                }),
                clearTrace: () => ({}),
            },
        ],
    }),

    selectors({
        trace: [
            (s) => [s.parsedTraceData],
            (parsedTraceData: ParsedTraceData | null): LLMTrace | undefined => parsedTraceData?.trace,
        ],
        enrichedTree: [
            (s) => [s.parsedTraceData],
            (parsedTraceData: ParsedTraceData | null): EnrichedTraceTreeNode[] => parsedTraceData?.enrichedTree || [],
        ],
        showableEvents: [
            (s) => [s.trace],
            (trace: LLMTrace | undefined): LLMTraceEvent[] => (trace ? trace.events : []),
        ],
        filteredTree: [
            (s) => [s.enrichedTree],
            (enrichedTree: EnrichedTraceTreeNode[]): TraceTreeNode[] => enrichedTree,
        ],
        initialFocusEventId: [
            (s) => [s.showableEvents, s.filteredTree],
            (showableEvents: LLMTraceEvent[], filteredTree: TraceTreeNode[]): string | null =>
                getInitialFocusEventId(showableEvents, filteredTree),
        ],
        effectiveEventId: [
            (s) => [s.selectedEventId, s.initialFocusEventId],
            (eventId: string | null, initialFocusEventId: string | null): string | null =>
                getEffectiveEventId(eventId, initialFocusEventId),
        ],
        event: [
            (s) => [s.trace, s.effectiveEventId, s.showableEvents],
            (
                trace: LLMTrace | undefined,
                effectiveEventId: string | null,
                showableEvents: LLMTraceEvent[]
            ): LLMTrace | LLMTraceEvent | null => {
                if (!trace) {
                    return null
                }

                if (!effectiveEventId || effectiveEventId === trace.id) {
                    return trace
                }

                if (!showableEvents?.length) {
                    return null
                }

                return showableEvents.find((event) => event.id === effectiveEventId) || null
            },
        ],
        eventMetadata: [
            (s) => [s.event],
            (event: LLMTrace | LLMTraceEvent | null): Record<string, unknown> | undefined => {
                if (event && isLLMEvent(event)) {
                    return Object.fromEntries(Object.entries(event.properties).filter(([key]) => !key.startsWith('$')))
                }

                return undefined
            },
        ],
        hasTrace: [
            (s) => [s.parsedTraceData],
            (parsedTraceData: ParsedTraceData | null): boolean => parsedTraceData !== null,
        ],
        inputMessageShowStates: [
            (s) => [s.messageShowStates],
            (messageStates: { input: boolean[]; output: boolean[] }) => messageStates.input,
        ],
        outputMessageShowStates: [
            (s) => [s.messageShowStates],
            (messageStates: { input: boolean[]; output: boolean[] }) => messageStates.output,
        ],
        eventTypeExpanded: [
            (s) => [s.eventTypeExpandedMap],
            (eventTypeExpandedMap: Record<string, boolean>) =>
                (eventType: string): boolean => {
                    return eventTypeExpandedMap[eventType] ?? true
                },
        ],
    }),

    listeners(({ actions, values }) => ({
        parseAndLoadTrace: () => {
            const rawJson = values.rawJson

            if (!rawJson.trim()) {
                actions.setValidationError(null)
                actions.setParsedTraceData(null)
                return
            }

            try {
                const data = JSON.parse(rawJson)
                const validation = validateTraceExport(data)

                if (!validation.valid) {
                    actions.setValidationError(validation.error || 'Invalid trace data')
                    actions.setParsedTraceData(null)
                    return
                }

                const result = parseTraceExportJson(rawJson)
                actions.setValidationError(null)
                actions.setParsedTraceData(result)
            } catch (e) {
                actions.setValidationError(e instanceof Error ? e.message : 'Failed to parse JSON')
                actions.setParsedTraceData(null)
            }
        },
    })),
])
