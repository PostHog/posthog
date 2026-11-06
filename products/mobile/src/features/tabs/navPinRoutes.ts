import type { Href, ImperativeRouter } from 'expo-router'

import type { NavPin } from './navPinStore'

// Both navigators share the public list URLs. Explicit groups keep a pushed list from resolving to a hidden tab.
const TAB_HREFS: Record<NavPin, Href> = { errors: '/(tabs)/errors', replay: '/(tabs)/replay' }
const STACK_HREFS: Record<NavPin, Href> = { errors: '/(stack)/errors', replay: '/(stack)/replay' }

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
