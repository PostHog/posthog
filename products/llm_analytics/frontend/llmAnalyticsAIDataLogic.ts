import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { NodeKind, TraceQuery } from '~/queries/schema/schema-general'

import type { llmAnalyticsAIDataLogicType } from './llmAnalyticsAIDataLogicType'

export interface AIData {
    input: unknown
    output: unknown
    tools: unknown
}

export interface LoadAIDataParams {
    eventId: string
    input: unknown
    output: unknown
    tools: unknown
    traceId?: string
    timestamp?: string
    /** True when the team is rolled out to read from `ai_events`. When false, the new path
     *  can't help — TraceQuery would just fall back to the shared `events` table, which
     *  post-strip-heavy has NULL heavy props. */
    aiEventsRolloutEnabled?: boolean
}

async function loadAIDataAsync(params: LoadAIDataParams): Promise<AIData> {
    const { eventId, input, output, tools, traceId, timestamp, aiEventsRolloutEnabled } = params

    // Passthrough: caller already has both sides of the conversation (e.g. the trace page
    // hydrates rows from the TraceQuery that has heavy props merged back). No fetch needed.
    if (input != null && output != null) {
        return { input, output, tools }
    }

    // Can't fetch without trace coordinates — fall back to whatever we were handed.
    // This includes events without $ai_trace_id, which predate the SDK's auto-assignment.
    if (!traceId || !timestamp) {
        return { input, output, tools }
    }

    // The ai_events read path is the only one that can recover heavy props for a stripped
    // event. If the team isn't rolled out, skip the fetch.
    if (!aiEventsRolloutEnabled) {
        return { input, output, tools }
    }

    // Post-strip events have NULL heavy props on the shared `events` table. Reuse the
    // existing TraceQuery pipeline (ai_events first, shared `events` on zero rows) to
    // fetch the event's heavy columns by (trace_id, event uuid). TraceQueryDateRange
    // auto-widens the window by ±10 minutes, so a single timestamp is sufficient.
    try {
        const traceQuery: TraceQuery = {
            kind: NodeKind.TraceQuery,
            traceId,
            dateRange: { date_from: timestamp, date_to: timestamp },
        }
        const response = await api.query(traceQuery)
        const event = response.results?.[0]?.events?.find((e) => e.id === eventId)
        if (!event) {
            return { input, output, tools }
        }
        const props = event.properties ?? {}
        return {
            input: props.$ai_input ?? props.$ai_input_state ?? input,
            output: props.$ai_output_choices ?? props.$ai_output_state ?? output,
            tools: props.$ai_tools ?? tools,
        }
    } catch (error) {
        console.warn('[llmAnalyticsAIDataLogic] failed to load heavy AI props via TraceQuery', error)
        return { input, output, tools }
    }
}

export const llmAnalyticsAIDataLogic = kea<llmAnalyticsAIDataLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'llmAnalyticsAIDataLogic']),

    actions({
        loadAIDataForEvent: (params: LoadAIDataParams) => params,
        clearAIDataForEvent: (eventId: string) => ({ eventId }),
        clearAllAIData: true,
    }),

    reducers({
        aiDataCache: [
            {} as Record<string, AIData>,
            {
                loadAIDataForEventSuccess: (state, { aiDataForEvent }) => ({
                    ...state,
                    [aiDataForEvent.eventId]: {
                        input: aiDataForEvent.input,
                        output: aiDataForEvent.output,
                        tools: aiDataForEvent.tools,
                    },
                }),
                clearAIDataForEvent: (state, { eventId }) => {
                    const { [eventId]: _, ...rest } = state
                    return rest
                },
                clearAllAIData: () => ({}),
            },
        ],
        loadingEventIds: [
            new Set<string>(),
            {
                loadAIDataForEvent: (state, params) => {
                    const newSet = new Set(state)
                    newSet.add(params.eventId)
                    return newSet
                },
                loadAIDataForEventSuccess: (state, { aiDataForEvent }) => {
                    const newSet = new Set(state)
                    newSet.delete(aiDataForEvent.eventId)
                    return newSet
                },
                loadAIDataForEventFailure: (state, params) => {
                    const newSet = new Set(state)
                    const { eventId } = params.errorObject
                    newSet.delete(eventId)
                    return newSet
                },
            },
        ],
    }),

    selectors({
        isEventLoading: [
            (s) => [s.loadingEventIds],
            (loadingEventIds): ((eventId: string) => boolean) => {
                return (eventId: string) => loadingEventIds.has(eventId)
            },
        ],
    }),

    loaders(() => ({
        aiDataForEvent: [
            null as (AIData & { eventId: string }) | null,
            {
                loadAIDataForEvent: async (params: LoadAIDataParams) => {
                    const data = await loadAIDataAsync(params)
                    return {
                        ...data,
                        eventId: params.eventId,
                    }
                },
            },
        ],
    })),
])
