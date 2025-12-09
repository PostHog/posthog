import { useActions, useValues } from 'kea'

import { llmAnalyticsAIDataLogic } from '../llmAnalyticsAIDataLogic'

export interface UseAIDataResult {
    input: unknown
    output: unknown
    isLoading: boolean
}

interface EventWithProperties {
    id?: string
    uuid?: string
    properties?: {
        $ai_input?: unknown
        $ai_output?: unknown
        $ai_output_choices?: unknown
        $ai_input_state?: unknown
        $ai_output_state?: unknown
        $ai_error?: unknown
    }
}

export function useAIData(event: EventWithProperties | null | undefined): UseAIDataResult {
    const { aiDataCache, isEventLoading } = useValues(llmAnalyticsAIDataLogic)
    const { loadAIDataForEvent } = useActions(llmAnalyticsAIDataLogic)

    const eventId = event?.id || event?.uuid || ''
    const input = event?.properties?.$ai_input
    const output = event?.properties?.$ai_output_choices

    if (!eventId || (input === undefined && output === undefined)) {
        return {
            input,
            output,
            isLoading: false,
        }
    }

    const cached = aiDataCache[eventId]
    const loading = isEventLoading(eventId)

    if (!cached && !loading && (input !== undefined || output !== undefined)) {
        loadAIDataForEvent({
            eventId,
            input,
            output,
        })
    }

    return {
        input: cached?.input,
        output: cached?.output,
        isLoading: loading || !cached,
    }
}
