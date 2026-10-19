import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { createPersistHydrationGate } from '@/lib/persistHydration'

export type DefaultPage = 'inbox' | 'chats' | 'views'

export type DefaultPageHref = '/inbox' | '/chats' | '/views'

export const DEFAULT_PAGES: readonly DefaultPage[] = ['inbox', 'chats', 'views']

const LABELS: Record<DefaultPage, string> = { inbox: 'Inbox', chats: 'Chats', views: 'Views' }

const HREFS: Record<DefaultPage, DefaultPageHref> = { inbox: '/inbox', chats: '/chats', views: '/views' }

export function defaultPageLabel(page: DefaultPage): string {
    return LABELS[page]
}

export function defaultPageHref(page: DefaultPage): DefaultPageHref {
    return HREFS[page]
}

function isDefaultPage(value: unknown): value is DefaultPage {
    return typeof value === 'string' && (DEFAULT_PAGES as readonly string[]).includes(value)
}

interface DefaultPageState {
    page: DefaultPage
    setPage: (page: DefaultPage) => void
}

const hydration = createPersistHydrationGate()

export const useDefaultPageStore = create<DefaultPageState>()(
    persist((set) => ({ page: 'inbox', setPage: (page) => set({ page }) }), {
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

/** True once the saved page has loaded, so the app does not open the inbox before it knows the choice. */
export function useDefaultPageHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

/** The route of the page the app opens on, read at call time by back and close actions that send the person home. */
export function currentDefaultPageHref(): DefaultPageHref {
    return defaultPageHref(useDefaultPageStore.getState().page)
}
