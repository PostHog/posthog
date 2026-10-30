import AsyncStorage from '@react-native-async-storage/async-storage'
import { type ColorSchemeName, Appearance as NativeAppearance } from 'react-native'

import { type Appearance, resolveColorScheme } from './appearanceStore'

const STORAGE_KEY = 'posthog-mobile-appearance'

type AppearanceStore = typeof import('./appearanceStore')['useAppearanceStore']

async function loadStore(): Promise<AppearanceStore> {
    let store: AppearanceStore | undefined
    jest.isolateModules(() => {
        store = jest.requireActual<typeof import('./appearanceStore')>('./appearanceStore').useAppearanceStore
    })
    if (!store) {
        throw new Error('Appearance store did not load')
    }
    await store.persist.rehydrate()
    return store
}

describe('appearance store', () => {
    afterEach(async () => {
        await AsyncStorage.clear()
    })

    test.each<[string, unknown, Appearance]>([
        ['a saved override', 'dark', 'dark'],
        ['a value this build does not know', 'sepia', 'system'],
        ['a non-string value', 1, 'system'],
    ])('loads %s (%p) as %s', async (_name, saved, expected) => {
        await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify({ state: { appearance: saved }, version: 0 }))
        const store = await loadStore()
        expect(store.getState().appearance).toBe(expected)
    })

    test.each<[Appearance, ColorSchemeName | null, 'light' | 'dark']>([
        ['system', 'dark', 'dark'],
        ['system', 'light', 'light'],
        ['system', null, 'light'],
        ['light', 'dark', 'light'],
        ['dark', 'light', 'dark'],
    ])('resolves %s on a %s device to %s', (appearance, deviceScheme, expected) => {
        expect(resolveColorScheme(appearance, deviceScheme)).toBe(expected)
    })

    test('pushes an override to the native appearance and restores the device scheme for system', async () => {
        const setColorScheme = jest.spyOn(NativeAppearance, 'setColorScheme').mockImplementation(() => undefined)
        const store = await loadStore()
        store.getState().setAppearance('dark')
        store.getState().setAppearance('system')
        expect(setColorScheme.mock.calls).toEqual([['dark'], ['unspecified']])
        setColorScheme.mockRestore()
    })
})
