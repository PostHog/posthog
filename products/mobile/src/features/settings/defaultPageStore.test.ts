import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'

import { DEFAULT_PAGES, type DefaultPage, defaultPageHref, effectiveDefaultPage } from './defaultPageStore'

const STORAGE_KEY = 'posthog-mobile-default-page'

type DefaultPageModule = typeof import('./defaultPageStore')
type DefaultPageStore = DefaultPageModule['useDefaultPageStore']

async function loadStore(): Promise<DefaultPageStore> {
    let store: DefaultPageStore | undefined
    jest.isolateModules(() => {
        store = jest.requireActual<DefaultPageModule>('./defaultPageStore').useDefaultPageStore
    })
    if (!store) {
        throw new Error('Default page store did not load')
    }
    await store.persist.rehydrate()
    return store
}

describe('default page store', () => {
    afterEach(async () => {
        await AsyncStorage.clear()
    })

    test('opens on Views when nothing is saved', async () => {
        const store = await loadStore()
        expect(store.getState().page).toBeNull()
        expect(effectiveDefaultPage(store.getState().page)).toBe('views')
    })

    test.each<DefaultPage>(DEFAULT_PAGES)('a chosen %s page survives a restart', async (page) => {
        const store = await loadStore()
        store.getState().setPage(page)
        await waitFor(async () => expect(await AsyncStorage.getItem(STORAGE_KEY)).toContain(`"${page}"`))

        const restarted = await loadStore()
        expect(effectiveDefaultPage(restarted.getState().page)).toBe(page)
    })

    test.each<[string, unknown]>([
        ['a removed tab', 'home'],
        ['a non-string value', 3],
    ])('treats %s as no choice', async (_name, saved) => {
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ state: { page: saved }, version: 0 }))
        const store = await loadStore()
        expect(store.getState().page).toBeNull()
    })

    test('every page maps to a tab route', () => {
        expect(DEFAULT_PAGES.map(defaultPageHref)).toEqual(['/inbox', '/chats', '/views', '/web-analytics', '/live'])
    })
})
