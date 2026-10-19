import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'

import { DEFAULT_PAGES, defaultPageHref } from './defaultPageStore'

const STORAGE_KEY = 'posthog-mobile-default-page'

type DefaultPageStore = typeof import('./defaultPageStore').useDefaultPageStore

async function loadStore(): Promise<DefaultPageStore> {
    let store: DefaultPageStore | undefined
    jest.isolateModules(() => {
        store = jest.requireActual<typeof import('./defaultPageStore')>('./defaultPageStore').useDefaultPageStore
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

    test('opens on the inbox when nothing is saved', async () => {
        const store = await loadStore()
        expect(store.getState().page).toBe('inbox')
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
    ])('falls back to the inbox for %s', async (_name, saved) => {
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ state: { page: saved }, version: 0 }))
        const store = await loadStore()
        expect(store.getState().page).toBe('inbox')
    })

    test('every page maps to a tab route', () => {
        expect(DEFAULT_PAGES.map(defaultPageHref)).toEqual(['/inbox', '/chats', '/views'])
    })
})
