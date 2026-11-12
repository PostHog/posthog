import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'

import { DEFAULT_PAGES, type DefaultPage, defaultPageHref, effectiveDefaultPage } from './defaultPageStore'

const STORAGE_KEY = 'posthog-mobile-default-page'

jest.mock('@/lib/analytics', () => ({ track: jest.fn(), trackWhenReady: jest.fn() }))

type DefaultPageModule = typeof import('./defaultPageStore')
type DefaultPageStore = DefaultPageModule['useDefaultPageStore']

interface IsolatedModules {
    store: DefaultPageStore
    analytics: typeof import('@/lib/analytics')
}

// A fresh registry per load, so each store hydrates from storage once, the way the app does at launch.
async function loadModules(): Promise<IsolatedModules> {
    let modules: IsolatedModules | undefined
    jest.isolateModules(() => {
        modules = {
            store: jest.requireActual<DefaultPageModule>('./defaultPageStore').useDefaultPageStore,
            analytics: jest.requireMock<typeof import('@/lib/analytics')>('@/lib/analytics'),
        }
    })
    if (!modules) {
        throw new Error('Default page store did not load')
    }
    const { store } = modules
    await waitFor(() => expect(store.persist.hasHydrated()).toBe(true))
    return modules
}

async function loadStore(): Promise<DefaultPageStore> {
    return (await loadModules()).store
}

async function save(page: unknown, version: number): Promise<void> {
    await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ state: { page }, version }))
}

describe('default page store', () => {
    afterEach(async () => {
        await AsyncStorage.clear()
        jest.clearAllMocks()
    })

    test('opens Home when nothing is saved', async () => {
        const store = await loadStore()
        expect(store.getState().page).toBeNull()
        expect(effectiveDefaultPage(store.getState().page)).toBe('live')
    })

    test.each<DefaultPage>(['inbox', 'views', 'live'])('a chosen %s page survives a restart', async (page) => {
        const store = await loadStore()
        store.getState().setPage(page)
        await waitFor(async () => expect(await AsyncStorage.getItem(STORAGE_KEY)).toContain(`"${page}"`))

        const restarted = await loadStore()
        expect(restarted.getState().page).toBe(page)
    })

    test.each<[string, unknown]>([
        ['a page the app does not have', 'web_analytics'],
        ['a non-string value', 3],
    ])('treats %s as no choice', async (_name, saved) => {
        await save(saved, 1)
        const store = await loadStore()
        expect(store.getState().page).toBeNull()
    })

    test.each<[string, number, DefaultPage | null, boolean]>([
        ['inbox', 0, null, true],
        ['web_analytics', 0, null, true],
        ['views', 0, 'views', false],
        ['live', 0, 'live', false],
        ['chats', 0, 'chats', false],
        ['inbox', 2, 'inbox', false],
    ])('moves a saved %s page from version %s to %s once', async (saved, version, page, migrated) => {
        await save(saved, version)
        const { store, analytics } = await loadModules()

        expect(store.getState().page).toBe(page)
        expect(jest.mocked(analytics.trackWhenReady).mock.calls).toEqual(
            migrated ? [['mobile_default_page_migrated', { from: saved, to: 'live' }]] : []
        )
        await waitFor(async () => expect(await AsyncStorage.getItem(STORAGE_KEY)).toContain('"version":1'))

        // Every isolated registry gets the same analytics mock, so the restart starts from an empty call list.
        jest.mocked(analytics.trackWhenReady).mockClear()
        const restarted = await loadModules()
        expect(restarted.store.getState().page).toBe(page)
        expect(restarted.analytics.trackWhenReady).not.toHaveBeenCalled()
    })

    test('every page maps to a tab route, with Home first', () => {
        expect(DEFAULT_PAGES.map(defaultPageHref)).toEqual(['/live', '/inbox', '/chats', '/views'])
    })
})
