export const urls = {
    llmObservabilityDashboard: (): string => '/llm-observability',
    llmObservabilityGenerations: (): string => '/llm-observability/generations',
    llmObservabilityTraces: (): string => '/llm-observability/traces',
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
    llmObservabilityUsers: (): string => '/llm-observability/users',
}
