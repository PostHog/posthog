import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'

export type DefaultPage = 'inbox' | 'chats' | 'views' | 'web_analytics' | 'live'

export type DefaultPageHref = '/inbox' | '/chats' | '/views' | '/web-analytics' | '/live'

export const DEFAULT_PAGES: readonly DefaultPage[] = ['inbox', 'chats', 'views', 'web_analytics', 'live']

const LABELS: Record<DefaultPage, string> = {
    inbox: 'Inbox',
    chats: 'Chats',
    views: 'Views',
    web_analytics: 'Web analytics',
    live: 'Live',
}

// The public paths of the (tabs) routes. Web analytics and Live open as their navigation tabs, pinned or not.
const HREFS: Record<DefaultPage, DefaultPageHref> = {
    inbox: '/inbox',
    chats: '/chats',
    views: '/views',
    web_analytics: '/web-analytics',
    live: '/live',
}

export function defaultPageLabel(page: DefaultPage): string {
    return LABELS[page]
}

export function defaultPageHref(page: DefaultPage): DefaultPageHref {
    return HREFS[page]
}

/** The page the app opens on while the person has not chosen one. */
export function effectiveDefaultPage(page: DefaultPage | null): DefaultPage {
    return page ?? 'views'
}

function isDefaultPage(value: unknown): value is DefaultPage {
    return typeof value === 'string' && (DEFAULT_PAGES as readonly string[]).includes(value)
}

interface DefaultPageState {
    page: DefaultPage | null
    setPage: (page: DefaultPage) => void
}

const hydration = createPersistHydrationGate()

export const useDefaultPageStore = create<DefaultPageState>()(
    persist((set) => ({ page: null, setPage: (page) => set({ page }) }), {
        name: 'posthog-mobile-default-page',
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ page: state.page }),
        // A saved page the app no longer has, such as a renamed tab, must not redirect to a missing route.
        merge: (persisted, current) => {
            const page =
                typeof persisted === 'object' && persisted !== null && 'page' in persisted ? persisted.page : null
            return isDefaultPage(page) ? { ...current, page } : current
        },
        onRehydrateStorage: () => () => hydration.settle(),
    })
)

export function useDefaultPageHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

/** The route of the page the app opens on, read at call time by back and close actions that send the person home. */
export function currentDefaultPageHref(): DefaultPageHref {
    return defaultPageHref(effectiveDefaultPage(useDefaultPageStore.getState().page))
}
