import type { TabKey } from './tabHeaderStore'

// Route names are the folder names under `app/(tabs)/`, and the public paths use dashes.
const ROUTES: Record<TabKey, string> = {
    live: 'live',
    inbox: 'inbox',
    chats: 'chats',
    views: 'views',
    errors: 'errors',
    replay: 'replay',
    web_analytics: 'web-analytics',
}

const TABS = Object.keys(ROUTES) as TabKey[]

/** The tabs the bar always shows, in bar order. Home is the Live screen and the first route. */
export const BAR_TABS: readonly TabKey[] = ['live', 'inbox', 'chats', 'views']

export function tabRouteName(tab: TabKey): string {
    return ROUTES[tab]
}

export function tabForRoute(name: string | undefined): TabKey {
    return TABS.find((tab) => ROUTES[tab] === name) ?? 'live'
}
