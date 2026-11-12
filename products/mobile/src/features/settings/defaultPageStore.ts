import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { trackWhenReady } from '@/lib/analytics'
import { createPersistHydrationGate } from '@/lib/persistHydration'

/** `live` is the Home tab. */
export type DefaultPage = 'live' | 'inbox' | 'chats' | 'views'

export type DefaultPageHref = '/live' | '/inbox' | '/chats' | '/views'

export const DEFAULT_PAGES: readonly DefaultPage[] = ['live', 'inbox', 'chats', 'views']

const LABELS: Record<DefaultPage, string> = {
    live: 'Home',
    inbox: 'Inbox',
    chats: 'Chats',
    views: 'Views',
}

// The public paths of the (tabs) routes.
const HREFS: Record<DefaultPage, DefaultPageHref> = {
    live: '/live',
    inbox: '/inbox',
    chats: '/chats',
    views: '/views',
}

export function defaultPageLabel(page: DefaultPage): string {
    return LABELS[page]
}

export function defaultPageHref(page: DefaultPage): DefaultPageHref {
    return HREFS[page]
}

/** The page the app opens on while the person has not chosen one. */
export function effectiveDefaultPage(page: DefaultPage | null): DefaultPage {
    return page ?? 'live'
}

function isDefaultPage(value: unknown): value is DefaultPage {
    return typeof value === 'string' && (DEFAULT_PAGES as readonly string[]).includes(value)
}

interface PersistedDefaultPage {
    /** Null until the person chooses a page in Settings. */
    page: DefaultPage | null
}

function savedPage(persisted: unknown): unknown {
    return typeof persisted === 'object' && persisted !== null && 'page' in persisted ? persisted.page : null
}

/**
 * Version 0 opened on the inbox and saved it for every person whose organization approved AI, so a saved inbox is not
 * a choice the person made. Web analytics is no longer a tab. Both go back to no choice, which opens Home.
 */
function migrateDefaultPage(persisted: unknown): PersistedDefaultPage {
    const from = savedPage(persisted)
    const page = from === 'inbox' || from === 'web_analytics' || !isDefaultPage(from) ? null : from
    if (typeof from === 'string' && from !== page) {
        trackWhenReady('mobile_default_page_migrated', { from, to: effectiveDefaultPage(page) })
    }
    return { page }
}

interface DefaultPageState extends PersistedDefaultPage {
    setPage: (page: DefaultPage) => void
}

const hydration = createPersistHydrationGate()

export const useDefaultPageStore = create<DefaultPageState>()(
    persist((set) => ({ page: null, setPage: (page) => set({ page }) }), {
        name: 'posthog-mobile-default-page',
        version: 1,
        migrate: migrateDefaultPage,
        storage: createJSONStorage(() => AsyncStorage),
        partialize: (state) => ({ page: state.page }),
        // A saved page the app does not have must not redirect to a missing route.
        merge: (persisted, current) => {
            const page = savedPage(persisted)
            return isDefaultPage(page) ? { ...current, page } : current
        },
        onRehydrateStorage: () => () => hydration.settle(),
    })
)

/** True once the saved page has loaded, so the app does not open Home before it knows the choice. */
export function useDefaultPageHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

/** The route of the page the app opens on, read at call time by back and close actions that send the person home. */
export function currentDefaultPageHref(): DefaultPageHref {
    return defaultPageHref(effectiveDefaultPage(useDefaultPageStore.getState().page))
}
