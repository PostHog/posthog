import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

export interface ActivitySummaryInput {
    totalCalls: number
    distinctClients: number
    errorCalls: number
    /** The busiest tool's name, when known. */
    topTool: string | null
}

/**
 * The activity stage's "key metric" is a sentence, not a tile grid: at low
 * volume the user's question is "what are agents doing with my server?", and a
 * plain-language answer beats six sparse KPIs. Serves the same intro job as the
 * one-time first-look hero, but persistent and tailored to early data.
 */
export function buildActivitySummary(input: ActivitySummaryInput): string {
    const { totalCalls, distinctClients, errorCalls, topTool } = input

    if (totalCalls === 0) {
        return 'Waiting for your first tool call…'
    }
    if (totalCalls <= 5) {
        return totalCalls === 1
            ? "Your first tool call arrived — here's what the agent tried."
            : `Your first ${totalCalls} tool calls arrived — here's what agents tried.`
    }

    const parts = [`${humanFriendlyLargeNumber(totalCalls)} tool calls`]
    if (distinctClients > 0) {
        parts.push(`from ${distinctClients} client${distinctClients === 1 ? '' : 's'}`)
    }
    let summary = `${parts.join(' ')} so far`
    if (topTool) {
        summary += ` — ${topTool} is the favorite`
    }
    if (errorCalls > 0) {
        summary += `${topTool ? ',' : ' —'} ${errorCalls} failure${errorCalls === 1 ? '' : 's'} worth a look`
    }
    return summary
}
