import { skipToken, useQuery } from '@tanstack/react-query'

import { inboxCacheKey, type SavedInbox } from '@/api/readCacheKeys'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoInboxQuery } from '@/demo/hooks'
import type { InboxItem } from '@/model/types'

function countUnread(items: readonly InboxItem[]): number {
    return items.filter((item) => !item.read).length
}

function hasUnread(items: readonly InboxItem[]): boolean {
    return items.some((item) => !item.read)
}

function savedUnreadCount(saved: SavedInbox): number {
    return countUnread(saved.items)
}

function savedHasUnread(saved: SavedInbox): boolean {
    return hasUnread(saved.items)
}

/**
 * A value of the inbox list the app last loaded: the first page the inbox saves in the query cache. It never fetches,
 * so it is null until the inbox has loaded once. `select` runs on the saved page, so a caller re-renders only when its
 * value changes; pass a function defined at module level.
 */
function useSavedInbox<T>(select: (saved: SavedInbox) => T, pick: (items: readonly InboxItem[]) => T): T | null {
    const mode = useDataMode()
    const scope = useProjectScope()
    const demo = useDemoInboxQuery()
    const saved = useQuery({ queryKey: inboxCacheKey(scope), queryFn: skipToken, select })
    if (mode === 'demo') {
        return demo.data ? pick(demo.data) : null
    }
    return mode === 'live' ? (saved.data ?? null) : null
}

/** Unread reports in the inbox list the app last loaded, or null until the inbox has loaded once. */
export function useInboxUnreadCount(): number | null {
    return useSavedInbox(savedUnreadCount, countUnread)
}

/** True when that list has an unread report, for the Inbox tab's dot. */
export function useInboxHasUnread(): boolean {
    return useSavedInbox(savedHasUnread, hasUnread) === true
}
