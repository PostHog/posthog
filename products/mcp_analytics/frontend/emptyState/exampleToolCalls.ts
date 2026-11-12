import type { BrandMarkName } from '../brandMarks'

export type ExampleHarness = 'claude' | 'cursor' | 'openai'

export interface ExampleToolCall {
    tool: string
    mark: BrandMarkName
    harness: ExampleHarness
    time: string
    error?: boolean
}

// Example tool calls - hand-authored, not real data. MCP tools are bare snake_case
// names (no parentheses - these are tool invocations, not function calls).
// `harness` tags a row for the filter chips.
export const EXAMPLE_TOOL_CALLS: ExampleToolCall[] = [
    { tool: 'search_docs', mark: 'Claude', harness: 'claude', time: '142ms' },
    { tool: 'create_issue', mark: 'Cursor', harness: 'cursor', time: 'err', error: true },
    { tool: 'run_query', mark: 'OpenAI', harness: 'openai', time: '210ms' },
    { tool: 'list_feature_flags', mark: 'Claude', harness: 'claude', time: '53ms' },
    { tool: 'get_schema', mark: 'Cursor', harness: 'cursor', time: '190ms' },
]
