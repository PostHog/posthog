import { useCallback, useEffect, useMemo, useRef, useSyncExternalStore } from 'react'

import { queryClient } from '@/api/queryClient'
import type { PaginatedApi } from '@/api/reports'
import type { FileSystemShortcutApi } from '@/api/shortcuts'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoViews } from '@/demo/views'
import { pinsFromShortcuts } from '@/model/adapters/viewPins'

import { trackViewsOpened } from '../analytics'
import { viewsKeys } from '../viewsCache'

const NO_PREFS = { rank: {}, display: {} }

/**
 * Sends `mobile_views_opened` each time the Views tab is selected. The tab bar calls it, because the bar stays mounted
 * across tab switches, so a return from a pushed view or a sheet does not count as an open. The pin count comes from
 * the cached pin list; on the first open of a session the event waits until the list has loaded.
 */
export function useViewsOpenedEvent(focused: boolean): void {
    const demo = useDataMode() === 'demo'
    const scope = useProjectScope()
    // Reads the pin list the Views screen loads, without fetching it from the tab bar.
    const subscribe = useCallback((listener: () => void) => queryClient.getQueryCache().subscribe(listener), [])
    const cached = useSyncExternalStore(subscribe, () =>
        queryClient.getQueryData<PaginatedApi<FileSystemShortcutApi>>(viewsKeys.shortcuts(demo ? null : scope))
    )
    const demoRows = useDemoViews((state) => state.shortcuts)
    const rows = demo ? demoRows : cached?.results
    const count = useMemo(() => (rows ? pinsFromShortcuts(rows, NO_PREFS).length : null), [rows])

    const pending = useRef<{ fromCache: boolean } | null>(null)
    // biome-ignore lint/correctness/useExhaustiveDependencies: an open is a change of `focused` only.
    useEffect(() => {
        pending.current = focused ? { fromCache: count !== null } : null
    }, [focused])
    useEffect(() => {
        if (focused && pending.current && count !== null) {
            trackViewsOpened({ pinnedCount: count, fromCache: pending.current.fromCache })
            pending.current = null
        }
    }, [focused, count])
}
