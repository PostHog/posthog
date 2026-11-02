import AsyncStorage from '@react-native-async-storage/async-storage'
import { useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

import { type AuthState, useAuthStore } from '@/auth/authStore'
import { type OrgAiStatus, projectOrganization } from '@/features/chat/aiAccess'
import { track } from '@/lib/analytics'
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

/** The page the app opens on while the person has not chosen one. */
export function effectiveDefaultPage(page: DefaultPage | null): DefaultPage {
    return page ?? 'inbox'
}

function isDefaultPage(value: unknown): value is DefaultPage {
    return typeof value === 'string' && (DEFAULT_PAGES as readonly string[]).includes(value)
}

interface DefaultPageState {
    /** Null until the person chooses a page in Settings or the app settles it once from the organization's AI status. */
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

/** True once the saved page has loaded, so the app does not open the inbox before it knows the choice. */
export function useDefaultPageHydrated(): boolean {
    return useSyncExternalStore(hydration.subscribe, hydration.isHydrated, hydration.isHydrated)
}

/** The route of the page the app opens on, read at call time by back and close actions that send the person home. */
export function currentDefaultPageHref(): DefaultPageHref {
    return defaultPageHref(effectiveDefaultPage(useDefaultPageStore.getState().page))
}

/**
 * A person who never chose a page starts on Views when the organization has not approved AI data processing, and on
 * the inbox when it has. `settle` is true when that result must be saved, which makes it permanent. An unknown status
 * saves nothing, so that a later launch with a known status decides.
 */
export function resolveStartPage(
    saved: DefaultPage | null,
    orgStatus: OrgAiStatus | null
): { page: DefaultPage; settle: boolean } {
    if (saved !== null || orgStatus === null || orgStatus === 'unknown') {
        return { page: effectiveDefaultPage(saved), settle: false }
    }
    return { page: orgStatus === 'approved' ? 'inbox' : 'views', settle: true }
}

/** The AI status of the selected project's organization, or null when no one is signed in. */
export function sessionOrgAiStatus(
    auth: Pick<AuthState, 'status' | 'organizations' | 'projects' | 'projectId'>
): OrgAiStatus | null {
    return auth.status === 'signed_in'
        ? projectOrganization(auth.organizations, auth.projects, auth.projectId).status
        : null
}

/** Resolves the page to open for a signed-in live session and saves it when the app settles it for the first time. */
export function settleDefaultPage(): DefaultPage {
    const orgStatus = sessionOrgAiStatus(useAuthStore.getState())
    const { page, settle } = resolveStartPage(useDefaultPageStore.getState().page, orgStatus)
    if (settle) {
        useDefaultPageStore.getState().setPage(page)
        track('mobile_default_page_defaulted', { page, org_ai_approved: orgStatus === 'approved' })
    }
    return page
}
