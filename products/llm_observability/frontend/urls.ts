import { LLMObservabilityTab } from "scenes/urls";

export const urls = {
    llmObservability: (tab?: LLMObservabilityTab): string =>
        `/llm-observability${tab !== 'dashboard' ? '/' + tab : ''}`,

}
