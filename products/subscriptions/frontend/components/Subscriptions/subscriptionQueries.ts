import { BreakPointFunction } from 'kea'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { subscriptionsList } from 'products/subscriptions/frontend/generated/api'

import { subscriptionsLogic } from './subscriptionsLogic'

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
    // If a subscriptionsLogic for this dashboard is already mounted (e.g. the subscriptions modal
    // was opened), reuse its data instead of refetching.
    const mounted = subscriptionsLogic.findMounted({ dashboardId })
    if (mounted && !mounted.values.subscriptionsLoading) {
        return mounted.values.subscriptions.length > 0
    }
    const response = await subscriptionsList(String(getCurrentTeamId()), { dashboard: dashboardId, limit: 1 })
    breakpoint?.()
    return (response.count ?? 0) > 0
}
