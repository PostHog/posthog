import { useCallback, useSyncExternalStore } from 'react'

import { queryClient } from '@/api/queryClient'
import { inboxCacheKey, type SavedInbox } from '@/api/readCacheKeys'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoInboxQuery } from '@/demo/hooks'
import type { InboxItem } from '@/model/types'

function hasUnread(items: readonly InboxItem[] | undefined): boolean {
    return items?.some((item) => !item.read) ?? false
}

/**
 * True when the inbox list the app last loaded has an unread report, for the dot on the Inbox tab. It reads the first
 * page that the inbox saves in the query cache and never fetches, so there is no dot until the inbox has loaded once.
 * Rows count as read until their read states load, so the dot never flashes on a list that has none.
 */
export function useInboxHasUnread(): boolean {
    const mode = useDataMode()
    const scope = useProjectScope()
    const demo = useDemoInboxQuery()
    const subscribe = useCallback((listener: () => void) => queryClient.getQueryCache().subscribe(listener), [])
    const live = useSyncExternalStore(subscribe, () =>
        hasUnread(queryClient.getQueryData<SavedInbox>(inboxCacheKey(scope))?.items)
    )
    if (mode === 'demo') {
        return hasUnread(demo.data)
    }
    return mode === 'live' && live
}
