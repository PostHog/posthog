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

/**
 * Prompts MUST backtick `$mcp_tool_call` and do it inside their first 120 characters. That is not
 * style — it is the only deterministic way to pin the event. `_pinned_event_names` (ai_subscription/
 * spec_generator.py) resolves an explicitly named event without asking an LLM, via two paths, and
 * both are positional:
 *   - quoted/backticked tokens, extracted by `_QUOTED_TOKEN_RE` from the whole prompt. Backtick the
 *     BARE name: a wider span like `event = '$mcp_tool_call'` is captured verbatim, matches no
 *     EventDefinition, and pins nothing.
 *   - bare standalone tokens, matched against a haystack that `_normalize_event_token` truncates to
 *     EVENT_NAME_MAX_LENGTH (120) — so a name mentioned later in the prompt is invisible to it.
 * Miss both and event choice falls through to a probabilistic LLM pass over every event in the
 * project's taxonomy, legacy names included. That is exactly how a report from this template came to
 * query the unprefixed `mcp_tool_call` and announce that no agent intent was recorded, over
 * instrumentation where 92% of calls carried one.
 *
 * The prose below is a second line of defence only. Deliberately does not backtick the legacy name:
 * quoted extraction reads the full prompt, so backticking it would pin the wrong event.
 */
const EVENT_NAME_DISAMBIGUATION =
    'If this project also has an older, unprefixed mcp_tool_call event, that one is legacy data ' +
    'and carries no $mcp_* properties.'

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
            'Summarize what AI agents were trying to do with our MCP server this week',
            'using `$mcp_tool_call` events and their $mcp_intent property.',
            EVENT_NAME_DISAMBIGUATION,
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
            'Report on our MCP server’s health for the last week using `$mcp_tool_call` events.',
            EVENT_NAME_DISAMBIGUATION,
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
