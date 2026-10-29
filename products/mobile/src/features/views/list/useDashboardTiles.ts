import { useEffect, useMemo, useState } from 'react'

import { errorQuery, loadingQuery, successQuery } from '@/model/queryStates'
import type { QueryState } from '@/model/types'
import type { DashboardView } from '@/model/views'

import { RECHECK_MS } from '../freshness'
import { type DashboardSnapshot, dashboardContainer, dashboardQueryKey } from '../items'
import { viewsQueue } from '../refreshQueue'
import { useViewsContext } from '../useViewsContext'
import { itemErrorMessage } from '../viewHooks'
import { freshnessKey, useItemError, useItemUpdating, useSnapshot } from '../viewsCache'

const GROUP = 'choose-tile'

export interface DashboardTiles {
    dashboard: QueryState<DashboardView>
    retry: () => void
}

/**
 * A dashboard's tiles for "Choose tile". It reuses the cached dashboard, and reads it again with
 * `refresh=force_cache` only when there is none or it is 5 minutes old. That read never computes, and it carries every
 * tile's cached result for the values in the list.
 */
export function useDashboardTiles(dashboardRef: string | null): DashboardTiles {
    const context = useViewsContext()
    const queryKey = dashboardRef ? dashboardQueryKey(context.scope, dashboardRef, null) : null
    const snapshot = useSnapshot<DashboardSnapshot>(queryKey)
    const key = queryKey ? freshnessKey(queryKey) : null
    const error = useItemError(key)
    // "Try again" shows the spinner while its read runs, not the error it answers.
    const updating = useItemUpdating(key)
    const [attempt, setAttempt] = useState(0)
    const { item, ready } = context

    useEffect(() => {
        if (!dashboardRef || !ready) {
            return undefined
        }
        const container = dashboardContainer(item, dashboardRef, null)
        const readAt = container.readAt()
        if (attempt === 0 && readAt !== null && Date.now() - readAt < RECHECK_MS) {
            return undefined
        }
        void viewsQueue.enqueue({
            key: container.key,
            family: container.family,
            group: GROUP,
            mode: 'force_cache',
            run: (_mode, signal) => container.read(signal),
            userRetry: attempt > 0,
        })
        return () => viewsQueue.leave(GROUP)
    }, [dashboardRef, ready, item, attempt])

    const view = snapshot?.view
    const dashboard = useMemo<QueryState<DashboardView>>(() => {
        if (view) {
            return successQuery(view)
        }
        if (error && !updating) {
            return errorQuery(new Error(itemErrorMessage(error)))
        }
        return loadingQuery()
    }, [view, error, updating])
    return { dashboard, retry: () => setAttempt((count) => count + 1) }
}
