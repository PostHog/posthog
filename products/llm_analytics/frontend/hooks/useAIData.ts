import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

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

    const eventId = eventData?.uuid
    const input = eventData?.input
    const output = eventData?.output
    const cached = eventId ? aiDataCache[eventId] : undefined
    const loading = eventId ? isEventLoading(eventId) : false

    useEffect(() => {
        if (!eventId || cached || loading) {
            return
        }

        loadAIDataForEvent({
            eventId,
            input,
            output,
        })
    }, [cached, loading, loadAIDataForEvent, eventId, input, output])

    if (!eventId) {
        return {
            input,
            output,
            isLoading: false,
        }
    }

    return {
        input: cached?.input,
        output: cached?.output,
        isLoading: loading || !cached,
    }
}
