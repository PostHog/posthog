import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'

export interface ActivitySummaryInput {
    lifetimeCalls: number | null
    totalCalls: number
    distinctClients: number
    errorCalls: number
    /** The busiest tool's name, when known. */
    topTool: string | null
}

export interface ActivitySummary {
    headline: string
    /** The failure count as a phrase ("4 failures"), or null when nothing failed. Rendered as a feed filter. */
    failures: string | null
}

/**
 * The activity stage's "key metric" is a sentence, not a tile grid: at low
 * volume the user's question is "what are agents doing with my server?", and a
 * plain-language answer beats six sparse KPIs. Serves the same intro job as the
 * one-time first-look hero, but persistent and tailored to early data.
 */
export function buildActivitySummary(input: ActivitySummaryInput): ActivitySummary {
    const { lifetimeCalls, totalCalls, distinctClients, errorCalls, topTool } = input
    const resolvedLifetimeCalls = lifetimeCalls === null ? null : Math.max(lifetimeCalls, totalCalls)
    const failures =
        totalCalls > 0 && errorCalls > 0
            ? `${humanFriendlyNumber(errorCalls)} failure${errorCalls === 1 ? '' : 's'}`
            : null

    if (totalCalls === 0) {
        return {
            headline:
                resolvedLifetimeCalls === 0 ? 'Waiting for your first tool call…' : 'No tool calls in the last 30 days',
            failures,
        }
    }
    if (resolvedLifetimeCalls !== null && resolvedLifetimeCalls <= 5) {
        return {
            headline:
                resolvedLifetimeCalls === 1
                    ? "Your first tool call arrived. Here's what the agent tried."
                    : `Your first ${resolvedLifetimeCalls} tool calls arrived. Here's what agents tried.`,
            failures,
        }
    }

    const parts = [`${humanFriendlyLargeNumber(totalCalls)} tool calls in the last 30 days`]
    if (distinctClients > 0) {
        parts.push(`from ${humanFriendlyNumber(distinctClients)} client${distinctClients === 1 ? '' : 's'}`)
    }
    let headline = parts.join(' ')
    if (topTool) {
        headline += `. ${topTool} is the favorite`
    }
    return { headline, failures }
}
