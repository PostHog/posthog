import { useActions, useValues } from 'kea'

import { llmAnalyticsAIDataLogic } from '../llmAnalyticsAIDataLogic'

export interface UseAIDataResult {
    input: unknown
    output: unknown
    isLoading: boolean
}

export interface EventData {
    uuid: string
    input: unknown
    output: unknown
}

export function useAIData(eventData: EventData | undefined): UseAIDataResult {
    const { aiDataCache, isEventLoading } = useValues(llmAnalyticsAIDataLogic)
    const { loadAIDataForEvent } = useActions(llmAnalyticsAIDataLogic)

    if (!eventData) {
        return { input: undefined, output: undefined, isLoading: false }
    }

    const cached = aiDataCache[eventData.uuid]
    const loading = isEventLoading(eventData.uuid)

    if (!cached && !loading) {
        loadAIDataForEvent({
            eventId: eventData.uuid,
            input: eventData.input,
            output: eventData.output,
        })
    }

    return {
        input: cached?.input,
        output: cached?.output,
        isLoading: loading || !cached,
    }
}
