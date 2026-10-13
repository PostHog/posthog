import type { ChatAgentMode } from '@/api/conversations'

export interface AgentModeOption {
    value: ChatAgentMode | null
    label: string
    description: string
}

/**
 * Labels and descriptions from `MODE_DEFINITIONS` and `SPECIAL_MODES` in `frontend/src/scenes/max/max-constants.tsx`,
 * in the web selector's order. Auto drops the web's second sentence, which points at a tool list the app does not show.
 */
export const AGENT_MODE_OPTIONS: readonly AgentModeOption[] = [
    {
        value: null,
        label: 'Auto',
        description: 'Automatically selects the best mode based on your request.',
    },
    {
        value: 'product_analytics',
        label: 'Product analytics',
        description: 'Creates insights and dashboards to analyze your product data.',
    },
    {
        value: 'sql',
        label: 'SQL',
        description: 'Generates and executes SQL queries for your PostHog data and connected data warehouse sources.',
    },
    {
        value: 'session_replay',
        label: 'Session replay',
        description: 'Analyzes session recordings and provides summaries and insights about user behavior.',
    },
    {
        value: 'error_tracking',
        label: 'Error tracking',
        description: 'Searches and analyzes error tracking issues to help you understand and fix bugs.',
    },
    {
        value: 'survey',
        label: 'Surveys',
        description: 'Creates and analyzes surveys to collect user feedback.',
    },
    {
        value: 'flags',
        label: 'Flags',
        description: 'Creates and manages feature flags and experiments.',
    },
    {
        value: 'llm_analytics',
        label: 'AI observability',
        description: 'Analyzes LLM traces and writes evaluation code for AI observability.',
    },
]

export function agentModeLabel(mode: ChatAgentMode | null): string {
    return AGENT_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? 'Auto'
}

export function agentModeKey(mode: ChatAgentMode | null): string {
    return mode ?? 'auto'
}
