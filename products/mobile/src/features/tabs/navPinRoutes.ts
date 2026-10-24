import type { Href, ImperativeRouter } from 'expo-router'

import type { NavPin } from './navPinStore'

// `/errors` names both the tab and the stack screen. A path without the group opens the stack screen, so the tab is
// reached through its group.
const TAB_HREFS: Record<NavPin, Href> = { errors: '/(tabs)/errors', replay: '/(tabs)/replay' }
const STACK_HREFS: Record<NavPin, Href> = { errors: '/errors', replay: '/replay' }

export function navTargetHref(pin: NavPin, pinned: boolean): Href {
    return pinned ? TAB_HREFS[pin] : STACK_HREFS[pin]
}

export function openNavTarget(router: Pick<ImperativeRouter, 'push' | 'navigate'>, pin: NavPin, pinned: boolean): void {
    if (pinned) {
        router.navigate(TAB_HREFS[pin])
        return
    }
    router.push(STACK_HREFS[pin])
}
