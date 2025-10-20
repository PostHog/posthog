import { actions, kea, path, reducers, selectors } from 'kea'

import type { llmAnalyticsTraceDebugLogicType } from './llmAnalyticsTraceDebugLogicType'

export const llmAnalyticsTraceDebugLogic = kea<llmAnalyticsTraceDebugLogicType>([
    path(['products', 'llm-analytics', 'llmAnalyticsTraceDebugLogic']),
    actions({
        setTraceJSON: (json: string) => ({ json }),
        clearTrace: true,
    }),
    reducers({
        rawTraceJSON: [
            '' as string,
            {
                setTraceJSON: (_, { json }) => json,
                clearTrace: () => '',
            },
        ],
        parseTimestamp: [
            0 as number,
            {
                setTraceJSON: () => Date.now(),
            },
        ],
    }),
    selectors({
        parsedTrace: [
            (s) => [s.rawTraceJSON, s.parseTimestamp],
            (rawTraceJSON, parseTimestamp): any | null => {
                if (!rawTraceJSON.trim()) {
                    return null
                }
                try {
                    // Include parseTimestamp in the dependency to force recalculation
                    const parsed = JSON.parse(rawTraceJSON)
                    // Add a timestamp to ensure object reference changes
                    return { ...parsed, _parseTimestamp: parseTimestamp }
                } catch {
                    return null
                }
            },
        ],
        traceFormat: [
            (s) => [s.parsedTrace],
            (parsedTrace): 'internal' | 'export' | null => {
                if (!parsedTrace) {
                    return null
                }
                // Detect format: internal format has 'events' array with '$ai_generation' event types
                // Export format has 'trace_id' and 'events' with 'type: generation'
                if (parsedTrace.events && parsedTrace.events.length > 0) {
                    const firstEvent = parsedTrace.events[0]
                    if (firstEvent.event && firstEvent.event.startsWith('$ai_')) {
                        return 'internal'
                    }
                    if (firstEvent.type === 'generation' || firstEvent.type === 'span') {
                        return 'export'
                    }
                }
                return null
            },
        ],
        parseError: [
            (s) => [s.rawTraceJSON, s.parsedTrace, s.traceFormat],
            (rawTraceJSON, parsedTrace, traceFormat): string | null => {
                if (!rawTraceJSON.trim()) {
                    return null
                }
                if (!parsedTrace) {
                    return 'Invalid JSON format'
                }

                // Check for internal format (preferred)
                if (traceFormat === 'internal') {
                    if (!parsedTrace.id) {
                        return 'Missing required field: id'
                    }
                    if (!parsedTrace.createdAt) {
                        return 'Missing required field: createdAt'
                    }
                    if (!Array.isArray(parsedTrace.events)) {
                        return 'Missing or invalid field: events (must be an array)'
                    }
                    return null
                }

                // Check for export format (fallback)
                if (traceFormat === 'export') {
                    if (!parsedTrace.trace_id) {
                        return 'Missing required field: trace_id'
                    }
                    if (!parsedTrace.timestamp) {
                        return 'Missing required field: timestamp'
                    }
                    if (!Array.isArray(parsedTrace.events)) {
                        return 'Missing or invalid field: events (must be an array)'
                    }
                    return null
                }

                return 'Unrecognized trace format. Please use either the raw trace data or exported trace JSON.'
            },
        ],
        isValidTrace: [
            (s) => [s.parsedTrace, s.parseError],
            (parsedTrace, parseError): boolean => {
                return parsedTrace !== null && parseError === null
            },
        ],
    }),
])
