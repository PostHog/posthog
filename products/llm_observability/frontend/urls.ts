export const urls = {
    llmObservability: (tab?: 'dashboard' | 'generations'): string =>
        `/llm-observability${tab !== 'dashboard' ? '/' + tab : ''}`,

}
