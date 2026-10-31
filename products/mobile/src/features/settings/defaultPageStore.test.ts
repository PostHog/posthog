import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'

import type { OrgAiStatus } from '@/features/chat/aiAccess'

import {
    DEFAULT_PAGES,
    type DefaultPage,
    defaultPageHref,
    effectiveDefaultPage,
    resolveStartPage,
} from './defaultPageStore'

const STORAGE_KEY = 'posthog-mobile-default-page'

jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

type DefaultPageModule = typeof import('./defaultPageStore')
type DefaultPageStore = DefaultPageModule['useDefaultPageStore']

interface IsolatedModules {
    defaultPage: DefaultPageModule
    auth: typeof import('@/auth/authStore')
    analytics: typeof import('@/lib/analytics')
}

// One registry for all three modules, so the stores and the mocked track are the instances settleDefaultPage uses.
async function loadModules(): Promise<IsolatedModules> {
    let modules: IsolatedModules | undefined
    jest.isolateModules(() => {
        modules = {
            defaultPage: jest.requireActual<DefaultPageModule>('./defaultPageStore'),
            auth: jest.requireActual<typeof import('@/auth/authStore')>('@/auth/authStore'),
            analytics: jest.requireMock<typeof import('@/lib/analytics')>('@/lib/analytics'),
        }
    })
    if (!modules) {
        throw new Error('Default page store did not load')
    }
    await modules.defaultPage.useDefaultPageStore.persist.rehydrate()
    return modules
}

async function loadStore(): Promise<DefaultPageStore> {
    return (await loadModules()).defaultPage.useDefaultPageStore
}

describe('default page store', () => {
    afterEach(async () => {
        await AsyncStorage.clear()
    })

    test('opens on the inbox when nothing is saved', async () => {
        const store = await loadStore()
        expect(store.getState().page).toBeNull()
        expect(effectiveDefaultPage(store.getState().page)).toBe('inbox')
    })

    test('a chosen page survives a restart', async () => {
        const store = await loadStore()
        store.getState().setPage('views')
        await waitFor(async () => expect(await AsyncStorage.getItem(STORAGE_KEY)).toContain('"views"'))

        const restarted = await loadStore()
        expect(restarted.getState().page).toBe('views')
    })

    test.each<[string, unknown]>([
        ['a removed tab', 'home'],
        ['a non-string value', 3],
    ])('treats %s as no choice', async (_name, saved) => {
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ state: { page: saved }, version: 0 }))
        const store = await loadStore()
        expect(store.getState().page).toBeNull()
    })

    test.each<[DefaultPage | null, OrgAiStatus, DefaultPage, boolean]>([
        [null, 'not_approved', 'views', true],
        [null, 'approved', 'inbox', true],
        [null, 'unknown', 'inbox', false],
        ['chats', 'not_approved', 'chats', false],
    ])('resolves saved page %s with organization %s to %s (settle: %s)', (saved, orgStatus, page, settle) => {
        expect(resolveStartPage(saved, orgStatus)).toEqual({ page, settle })
    })

    test("settles once on views when the selected project's organization has not approved AI", async () => {
        const { defaultPage, auth, analytics } = await loadModules()
        auth.useAuthStore.setState({
            status: 'signed_in',
            organizations: [
                { id: 'org-a', name: 'A', aiDataProcessingApproved: false },
                { id: 'org-b', name: 'B', aiDataProcessingApproved: true },
            ],
            projects: [
                { id: 1, name: 'One', organizationId: 'org-a', organizationName: 'A' },
                { id: 2, name: 'Two', organizationId: 'org-b', organizationName: 'B' },
            ],
            projectId: 1,
        })

        expect(defaultPage.settleDefaultPage()).toBe('views')
        await waitFor(async () => expect(await AsyncStorage.getItem(STORAGE_KEY)).toContain('"views"'))
        expect(analytics.track).toHaveBeenCalledTimes(1)
        expect(analytics.track).toHaveBeenCalledWith('mobile_default_page_defaulted', {
            page: 'views',
            org_ai_approved: false,
        })

        expect(defaultPage.settleDefaultPage()).toBe('views')
        expect(analytics.track).toHaveBeenCalledTimes(1)
    })

    test('every page maps to a tab route', () => {
        expect(DEFAULT_PAGES.map(defaultPageHref)).toEqual(['/inbox', '/chats', '/views'])
    })
})
