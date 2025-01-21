// import { LLMObservabilityTab } from "scenes/urls";
// TODO: get the enum back
// TODO: use kea-router to combine the url and params and process the timestamp.

export const urls = {
    llmObservability: (tab?: 'dashboard' | 'traces' | 'generations'): string =>
        `/llm-observability${tab !== 'dashboard' ? '/' + tab : ''}`,
    llmObservabilityTrace: (
        id: string,
        params?: {
            event?: string
            timestamp: string
        }
    ): string => {
        const queryParams = new URLSearchParams(params)
        const stringifiedParams = queryParams.toString()
        return `/llm-observability/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
    },
}
