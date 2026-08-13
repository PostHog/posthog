import { BreakPointFunction } from 'kea'

import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { getInsightId } from 'scenes/insights/utils'

import { InsightShortId } from '~/types'

import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

// Both queries reject on a failed request. Each caller decides what that means: a kea loader lets
// it reach its own `...Failure` action, a plain caller catches it.

export async function fetchTeamSubscriptionCount(breakpoint?: BreakPointFunction): Promise<number> {
    // limit=1 keeps the payload tiny; `count` reflects the team's full total.
    const response = await subscriptionsList(String(getCurrentTeamId()), { limit: 1 })
    breakpoint?.()
    return response.count ?? 0
}

export async function fetchHasSubscriptionForDashboard(
    dashboardId: number,
    breakpoint?: BreakPointFunction
): Promise<boolean> {
    const response = await subscriptionsList(String(getCurrentTeamId()), { dashboard: dashboardId, limit: 1 })
    breakpoint?.()
    return (response.count ?? 0) > 0
}

// Takes the short id because that is what the app carries around; the numeric id comes from the
// mounted insight where there is one, and costs a lookup otherwise.
export async function fetchHasSubscriptionForInsight(
    insightShortId: InsightShortId,
    breakpoint?: BreakPointFunction
): Promise<boolean> {
    const insightId = await getInsightId(insightShortId)
    breakpoint?.()
    if (!insightId) {
        return false
    }
    const response = await subscriptionsList(String(getCurrentTeamId()), { insight: insightId, limit: 1 })
    breakpoint?.()
    return (response.count ?? 0) > 0
}
