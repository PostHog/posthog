import type { TabKey } from './tabHeaderStore'

// Route names are the folder names under `app/(tabs)/`, and the public paths use dashes.
const ROUTES: Record<TabKey, string> = {
    inbox: 'inbox',
    chats: 'chats',
    views: 'views',
    errors: 'errors',
    replay: 'replay',
    web_analytics: 'web-analytics',
    live: 'live',
}

const TABS = Object.keys(ROUTES) as TabKey[]

export function tabRouteName(tab: TabKey): string {
    return ROUTES[tab]
}

export function tabForRoute(name: string | undefined): TabKey {
    return TABS.find((tab) => ROUTES[tab] === name) ?? 'inbox'
}
