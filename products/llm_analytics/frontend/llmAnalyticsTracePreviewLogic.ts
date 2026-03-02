import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import {
    EnrichedTraceTreeNode,
    getEffectiveEventId,
    getInitialFocusEventId,
    resolveTraceEventById,
} from './llmAnalyticsTraceDataLogic'
import type { llmAnalyticsTracePreviewLogicType } from './llmAnalyticsTracePreviewLogicType'
import { parseTraceExportJson } from './traceImportUtils'

export interface ParsedTraceData {
    trace: LLMTrace
    enrichedTree: EnrichedTraceTreeNode[]
}

export const llmAnalyticsTracePreviewLogic = kea<llmAnalyticsTracePreviewLogicType>([
    path(['scenes', 'llm-analytics', 'llmAnalyticsTracePreviewLogic']),

    actions({
        setRawJson: (json: string) => ({ json }),
        parseAndLoadTrace: true,
        setParsedTraceData: (data: ParsedTraceData | null) => ({ data }),
        setValidationError: (error: string | null) => ({ error }),
        clearTrace: true,
        setSelectedEventId: (eventId: string | null) => ({ eventId }),
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
                setParsedTraceData: () => null,
                clearTrace: () => null,
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
        showableEvents: [(s) => [s.trace], (trace: LLMTrace | undefined): LLMTraceEvent[] => trace?.events || []],
        initialFocusEventId: [
            (s) => [s.showableEvents, s.enrichedTree],
            (showableEvents: LLMTraceEvent[], enrichedTree: EnrichedTraceTreeNode[]): string | null =>
                getInitialFocusEventId(showableEvents, enrichedTree, null),
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

                return resolveTraceEventById(showableEvents, effectiveEventId)
            },
        ],
        hasTrace: [
            (s) => [s.parsedTraceData],
            (parsedTraceData: ParsedTraceData | null): boolean => parsedTraceData !== null,
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
