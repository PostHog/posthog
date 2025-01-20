import { LLMObservabilityTab } from "scenes/urls";

export const urls = {
    llmObservability: (tab?: LLMObservabilityTab): string =>
        `/llm-observability${tab !== 'dashboard' ? '/' + tab : ''}`,
    llmObservabilityTrace: (id: string, eventId?: string): string =>
        `/llm-observability/traces/${id}${eventId ? `?event=${eventId}` : ''}`,
}
