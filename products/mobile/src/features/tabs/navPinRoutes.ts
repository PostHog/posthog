import type { Href, ImperativeRouter } from 'expo-router'

import { webAnalyticsHref } from '@/features/views/viewRoutes'
import type { ViewEntry } from '@/model/views'

import type { NavPin } from './navPinStore'

// Errors and Sessions share their public list URLs with their tabs. Explicit groups keep a pushed list from resolving
// to a hidden tab. Web analytics keeps its pushed `/views/web-analytics` route, which deep links also open.
const TAB_HREFS: Record<NavPin, Href> = {
    errors: '/(tabs)/errors',
    replay: '/(tabs)/replay',
    web_analytics: '/(tabs)/web-analytics',
}

function stackHref(pin: NavPin, from: ViewEntry | undefined): Href {
    switch (pin) {
        case 'errors':
            return '/(stack)/errors'
        case 'replay':
            return '/(stack)/replay'
        case 'web_analytics':
            return webAnalyticsHref({ from })
    }
}

/** `from` names the entry for the open event of a pushed Web analytics screen. */
export function navTargetHref(pin: NavPin, pinned: boolean, from?: ViewEntry): Href {
    return pinned ? TAB_HREFS[pin] : stackHref(pin, from)
}

export function openNavTarget(
    router: Pick<ImperativeRouter, 'push' | 'navigate'>,
    pin: NavPin,
    pinned: boolean,
    from?: ViewEntry
): void {
    if (pinned) {
        router.navigate(TAB_HREFS[pin])
        return
    }
    router.push(stackHref(pin, from))
}
