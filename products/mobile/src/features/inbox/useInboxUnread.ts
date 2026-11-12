import { skipToken, useQuery } from '@tanstack/react-query'

import { inboxCacheKey, type SavedInbox } from '@/api/readCacheKeys'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoInboxQuery } from '@/demo/hooks'
import type { InboxItem } from '@/model/types'

function unreadCount(items: readonly InboxItem[] | undefined): number | null {
    return items ? items.filter((item) => !item.read).length : null
}

function savedUnreadCount(saved: SavedInbox): number | null {
    return unreadCount(saved.items)
}

/**
 * Unread reports in the inbox list the app last loaded. It reads the first page the inbox saves in the query cache and
 * never fetches, so it is null until the inbox has loaded once.
 */
export function useInboxUnreadCount(): number | null {
    const mode = useDataMode()
    const scope = useProjectScope()
    const demo = useDemoInboxQuery()
    const saved = useQuery({ queryKey: inboxCacheKey(scope), queryFn: skipToken, select: savedUnreadCount })
    if (mode === 'demo') {
        return unreadCount(demo.data)
    }
    return mode === 'live' ? (saved.data ?? null) : null
}

/** True when that list has an unread report, for the Inbox tab's dot. */
export function useInboxHasUnread(): boolean {
    return (useInboxUnreadCount() ?? 0) > 0
}
