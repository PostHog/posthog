import { skipToken, useQuery } from '@tanstack/react-query'

import { inboxCacheKey, type SavedInbox } from '@/api/readCacheKeys'
import { useProjectScope } from '@/auth/useProjectScope'
import { useDataMode } from '@/demo/demoMode'
import { useDemoInboxQuery } from '@/demo/hooks'
import type { InboxItem } from '@/model/types'

function hasUnread(items: readonly InboxItem[] | undefined): boolean {
    return items?.some((item) => !item.read) ?? false
}

function savedHasUnread(saved: SavedInbox): boolean {
    return hasUnread(saved.items)
}

/** True when the inbox had an unread report the last time it loaded; it reads the saved first page and never fetches. */
export function useInboxHasUnread(): boolean {
    const mode = useDataMode()
    const scope = useProjectScope()
    const demo = useDemoInboxQuery()
    const saved = useQuery({ queryKey: inboxCacheKey(scope), queryFn: skipToken, select: savedHasUnread })
    if (mode === 'demo') {
        return hasUnread(demo.data)
    }
    return mode === 'live' && saved.data === true
}
