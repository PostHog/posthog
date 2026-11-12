import { skipToken, useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { inboxCacheKey, type SavedInbox } from '@/api/readCacheKeys'
import { useDemoInboxQuery } from '@/demo/hooks'
import { usePins } from '@/features/views/pinHooks'
import { resolvePinDisplays } from '@/features/views/smartPinDisplay'
import { useCachedSmartPinDisplays } from '@/features/views/useSmartPinDisplays'
import { useViewsContext } from '@/features/views/useViewsContext'
import type { InboxItem } from '@/model/types'
import type { PinView } from '@/model/views'

/** Two pins keep the Inbox row on screen above the bottom bar. */
const MEANWHILE_PINS = 2

export interface LiveMeanwhile {
    /** The first pins in Views order, each with the display the Views list last chose for it. */
    pins: PinView[]
    /** Unread reports in the inbox list the app last loaded. Null until the inbox has loaded once. */
    unread: number | null
}

export function unreadCount(items: readonly InboxItem[] | undefined): number | null {
    return items ? items.filter((item) => !item.read).length : null
}

/**
 * What a Quiet or Not set up Live offers instead of live data. Pin numbers and the unread count come from what Views
 * and the inbox last read, so this sends no data reads. Only the pin list is read, once, when nothing has read it yet.
 */
export function useLiveMeanwhile(): LiveMeanwhile {
    const context = useViewsContext()
    const { pins, displayPrefs } = usePins()
    const automatic = useCachedSmartPinDisplays(pins.data, displayPrefs)
    const shown = useMemo(
        () => resolvePinDisplays((pins.data ?? []).slice(0, MEANWHILE_PINS), displayPrefs, automatic),
        [pins.data, displayPrefs, automatic]
    )
    const demoInbox = useDemoInboxQuery()
    const saved = useQuery<SavedInbox>({ queryKey: inboxCacheKey(context.scope), queryFn: skipToken })
    const items = context.mode === 'demo' ? demoInbox.data : saved.data?.items
    return { pins: shown, unread: unreadCount(items) }
}
