import { combineUrl } from 'kea-router'

import type { Dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import type { subscriptionsCreate } from 'products/subscriptions/frontend/generated/api'
import {
    RecurrenceIntervalEnumApi,
    SubscriptionAIWindowModeEnumApi,
    SubscriptionTargetEnumApi,
    SubscriptionWriteApiByweekdayItem,
} from 'products/subscriptions/frontend/generated/api.schemas'

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
    /** What a delivery covers, in the reader's terms, one short line each. */
    covers: string[]
}

export const TOOL_HEALTH_REPORT: MCPRecurringReport = {
    key: 'tool-health',
    headline: 'How your tools held up',
    lead: 'Volume, error rate and latency per tool, with the failures worth acting on.',
    // Weekly, not daily: a typical MCP server sees a few dozen calls a day, so a daily error
    // rate or p95 is noise. A week gives those numbers enough data to mean something.
    frequency: 'weekly',
    title: 'MCP tool health',
    prompt: [
        'Report on our MCP server’s health for the last week using $mcp_tool_call events.',
        'Cover total calls and calls per tool. Use $mcp_exec_tool_call_name when non-empty.',
        'Otherwise, for $mcp_tool_name = exec and $mcp_exec_verb = call, use $mcp_exec_target_tool',
        'when it is non-empty and not unrecognized. Fall back to $mcp_tool_name in all other cases.',
        'Include discovery requests under exec, not the tool they describe. Cover',
        'the error rate from $mcp_is_error, the most common $mcp_error_type values with example',
        '$mcp_error_message text, and p95 of $mcp_duration_ms per tool.',
        'Highlight tools whose error rate or latency is clearly worse than the weeks before,',
        'and skip sections where nothing notable happened.',
    ].join(' '),
    covers: [
        'Total calls and calls per tool',
        'Error rate, the most common error types and example messages',
        'p95 latency per tool',
        'Tools whose errors or latency got clearly worse than the weeks before',
    ],
}

export const MCP_RECURRING_REPORTS: MCPRecurringReport[] = [
    {
        key: 'intent-roundup',
        headline: 'What agents are trying to do',
        lead: 'Their goals in their own words, grouped and ranked, with the ones that keep failing called out.',
        frequency: 'weekly',
        title: 'MCP intent roundup',
        // This report infers an unmet intent from the error flag on a tool call. Explicit
        // $mcp_missing_capability reports stay in the Missing capabilities tab.
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
        covers: [
            "Agent goals grouped and ranked by how often they came up, quoted in the agents' own words",
            'The share of each goal that ended in a failed tool call',
            'Goals that are new compared with previous weeks',
            'One change to your tools that would help the most agents',
        ],
    },
    TOOL_HEALTH_REPORT,
]

/**
 * Opens the AI-subscription form with the report already written, so setting one up is choosing a
 * destination and a cadence rather than composing a prompt.
 */
export function urlForRecurringReport(
    report: MCPRecurringReport,
    targetType: SubscriptionTargetEnumApi | null
): string {
    return combineUrl(urls.subscriptionNew(), {
        resource_type: 'ai_prompt',
        prompt: report.prompt,
        title: report.title,
        frequency: report.frequency,
        target_type: targetType ?? undefined,
    }).url
}

type SubscriptionCreateBody = Parameters<typeof subscriptionsCreate>[1]

/**
 * The report emailed to `email`, first on the next day at 09:00 in the caller's time zone and then
 * every week. There is no immediate send: a report over a few minutes of data is thin, and the point is
 * a reason to come back on a later day.
 *
 * The server evaluates `byweekday` in UTC against `start_date`, so the weekday is the UTC weekday of the
 * first delivery. The local weekday would push the first delivery a day late wherever the two differ.
 */
export function weeklyReportPayload(report: MCPRecurringReport, email: string, now: Dayjs): SubscriptionCreateBody {
    const firstDelivery = now.add(1, 'day').hour(9).minute(0).second(0).millisecond(0)
    return {
        title: report.title,
        prompt: report.prompt,
        ai_prompt_config: { window: { mode: SubscriptionAIWindowModeEnumApi.SinceLastSent } },
        target_type: SubscriptionTargetEnumApi.Email,
        target_value: email,
        frequency: RecurrenceIntervalEnumApi.Weekly,
        interval: 1,
        byweekday: [firstDelivery.utc().format('dddd').toLowerCase() as SubscriptionWriteApiByweekdayItem],
        start_date: firstDelivery.toISOString(),
        send_test_now: false,
    }
}
