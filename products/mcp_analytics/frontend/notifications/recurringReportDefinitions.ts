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
        headline: 'What agents are trying to do',
        lead: 'Their goals in their own words, grouped and ranked, with the ones that keep failing called out.',
        frequency: 'weekly',
        title: 'MCP intent roundup',
        // Reads $mcp_intent on tool calls rather than $mcp_missing_capability: that event has never
        // been emitted by any project, while $mcp_intent is set on ~88% of calls. "Couldn't do it"
        // is inferred from the error flag on the same call, which is a signal that actually exists.
        prompt: [
            'Summarize what AI agents were trying to do with our MCP server this week,',
            'using the $mcp_intent property on $mcp_tool_call events.',
            'Group similar intents together and rank the groups by how often they came up,',
            'quoting one or two verbatim $mcp_intent examples per group.',
            'For each group, give the share of those calls that failed ($mcp_is_error) — an intent',
            'agents keep attempting and keep failing is the most useful thing in this report.',
            'Call out intents that are new compared with previous weeks, and finish with the single',
            'change to our tools that would help the most agents.',
        ].join(' '),
    },
    {
        key: 'tool-health',
        headline: 'How your tools held up',
        lead: 'Volume, error rate and latency per tool, with the failures worth acting on.',
        // Weekly, not daily: a typical MCP server sees a few dozen calls a day, so a daily error
        // rate or p95 is noise. A week gives those numbers enough data to mean something.
        frequency: 'weekly',
        title: 'MCP tool health',
        prompt: [
            'Report on our MCP server’s health for the last week using $mcp_tool_call events.',
            'Cover total calls, calls per tool (use $mcp_exec_tool_call_name when set, else $mcp_tool_name),',
            'the error rate from $mcp_is_error, the most common $mcp_error_type values with example',
            '$mcp_error_message text, and p95 of $mcp_duration_ms per tool.',
            'Highlight tools whose error rate or latency is clearly worse than the weeks before,',
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
