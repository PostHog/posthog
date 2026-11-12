import { useMemo } from 'react'

import { useInboxUnreadCount } from '@/features/inbox/useInboxUnread'
import { usePins } from '@/features/views/pinHooks'
import { resolvePinDisplays } from '@/features/views/smartPinDisplay'
import { useCachedSmartPinDisplays } from '@/features/views/useSmartPinDisplays'
import type { PinView } from '@/model/views'

/** Two pins keep the Inbox row on screen above the bottom bar. */
const MEANWHILE_PINS = 2

export interface LiveMeanwhile {
    /** The first pins in Views order, each with the display the Views list last chose for it. */
    pins: PinView[]
    /** Unread reports in the inbox list the app last loaded. Null until the inbox has loaded once. */
    unread: number | null
}

/**
 * What a Quiet or Not set up Live offers instead of live data. Pin numbers and the unread count come from what Views
 * and the inbox last read, so this sends no data reads. Only the pin list is read, once, when nothing has read it yet.
 */
export function useLiveMeanwhile(): LiveMeanwhile {
    const { pins, displayPrefs } = usePins()
    const automatic = useCachedSmartPinDisplays(pins.data, displayPrefs)
    const shown = useMemo(
        () => resolvePinDisplays((pins.data ?? []).slice(0, MEANWHILE_PINS), displayPrefs, automatic),
        [pins.data, displayPrefs, automatic]
    )
    return { pins: shown, unread: useInboxUnreadCount() }
}
