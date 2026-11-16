import type { ImperativeRouter } from 'expo-router'

import { openNavTarget } from '@/features/tabs/navPinRoutes'
import type { NavPin } from '@/features/tabs/navPinStore'

import { type BrowseEntry, browseEntryPin } from './BrowseEntryRow'

/** Opens a Browse row. Web analytics passes `browse` on, because its screen sends its own open event with the entry. */
export function openBrowseEntry(
    router: Pick<ImperativeRouter, 'push' | 'navigate'>,
    entry: BrowseEntry,
    isPinned: (pin: NavPin) => boolean
): void {
    if (entry === 'web') {
        openNavTarget(router, 'web_analytics', isPinned('web_analytics'), 'browse')
        return
    }
    const pin = browseEntryPin(entry)
    if (pin) {
        openNavTarget(router, pin, isPinned(pin))
        return
    }
    router.push(`/views/browse/${entry}`)
}
