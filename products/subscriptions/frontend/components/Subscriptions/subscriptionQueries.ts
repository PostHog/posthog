import { BreakPointFunction } from 'kea'

import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { getInsightId } from 'scenes/insights/utils'

import { InsightShortId } from '~/types'

import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

export async function fetchTeamSubscriptionCount(breakpoint?: BreakPointFunction): Promise<number> {
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

export async function fetchHasSubscriptionForInsightId(
    insightId: number,
    breakpoint?: BreakPointFunction
): Promise<boolean> {
    const response = await subscriptionsList(String(getCurrentTeamId()), { insight: insightId, limit: 1 })
    breakpoint?.()
    return (response.count ?? 0) > 0
}

export async function fetchHasSubscriptionForInsight(
    insightShortId: InsightShortId,
    breakpoint?: BreakPointFunction
): Promise<boolean> {
    const insightId = await getInsightId(insightShortId)
    breakpoint?.()
    return insightId ? await fetchHasSubscriptionForInsightId(insightId, breakpoint) : false
}
