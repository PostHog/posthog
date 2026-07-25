import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

export interface MCPRecurringReport {
    key: string
    headline: string
    lead: string
    frequency: 'daily' | 'weekly'
    title: string
    /**
     * Handed to the AI-subscription planner, which writes and runs its own HogQL. Names the
     * $mcp_* properties explicitly so it queries the right ones rather than guessing.
     */
    prompt: string
}

export const MCP_RECURRING_REPORTS: MCPRecurringReport[] = [
    {
        key: 'intent-roundup',
        headline: 'What agents keep asking for',
        lead: "The capabilities they wanted and couldn't find, ranked. The closest thing to a roadmap you'll get.",
        frequency: 'weekly',
        title: 'MCP intent roundup',
        prompt: [
            'Summarize what AI agents tried to do with our MCP server this week.',
            'Use $mcp_missing_capability events and the $mcp_intent property on $mcp_tool_call events.',
            'Rank the most common things agents asked for that our tools could not do, with a count for each',
            'and one or two verbatim $mcp_intent examples per group.',
            'Call out anything new compared with previous weeks, and finish with the single capability',
            'that would unblock the most agents.',
        ].join(' '),
    },
    {
        key: 'tool-health',
        headline: 'How your tools held up',
        lead: 'Volume, error rate and latency per tool, with the failures worth acting on.',
        frequency: 'daily',
        title: 'MCP tool health',
        prompt: [
            'Report on our MCP server’s health for the last day using $mcp_tool_call events.',
            'Cover total calls, calls per tool (use $mcp_exec_tool_call_name when set, else $mcp_tool_name),',
            'the error rate from $mcp_is_error, the most common $mcp_error_type values with example',
            '$mcp_error_message text, and p95 of $mcp_duration_ms per tool.',
            'Highlight tools whose error rate or latency is clearly worse than the days before,',
            'and skip sections where nothing notable happened.',
        ].join(' '),
    },
]

/**
 * Opens the AI-subscription form with the report already written, so setting one up is choosing a
 * destination and a cadence rather than composing a prompt.
 */
export function urlForRecurringReport(report: MCPRecurringReport): string {
    return combineUrl(urls.subscriptionNew(), {
        resource_type: 'ai_prompt',
        prompt: report.prompt,
        title: report.title,
        frequency: report.frequency,
        target_type: 'slack',
    }).url
}
