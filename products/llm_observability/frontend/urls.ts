// import { LLMObservabilityTab } from "scenes/urls";
// TODO: get the enum back

export const urls = {
    llmObservability: (tab?: 'dashboard' | 'traces' | 'generations'): string =>
        `/llm-observability${tab !== 'dashboard' ? '/' + tab : ''}`,
    llmObservabilityTrace: (id: string, eventId?: string): string =>
        `/llm-observability/traces/${id}${eventId ? `?event=${eventId}` : ''}`,
}
