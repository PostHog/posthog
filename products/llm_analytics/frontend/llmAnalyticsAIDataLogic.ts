import { actions, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { llmAnalyticsAIDataLogicType } from './llmAnalyticsAIDataLogicType'

export interface AIData {
    input: unknown
    output: unknown
}

export interface LoadAIDataParams {
    eventId: string
    input: unknown
    output: unknown
}

async function loadAIDataAsync(params: LoadAIDataParams): Promise<AIData> {
    const { input, output } = params
    if (!input && !output) {
        return { input, output }
    }

    // TODO: Once we store pointers to input and output, here is where we will load
    // them async. For the moment we just return the data as is, because it is
    // stored inline. Uncomment the following line in dev to see loading states:
    // await new Promise((resolve) => setTimeout(resolve, 2000))

    return {
        input,
        output,
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
