import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'

import { type NavPin, nextNavPins, replacedNavPin } from './navPinStore'

const STORAGE_KEY = 'nav-pins:v1'

type NavPinModule = typeof import('./navPinStore')

describe('navPinStore', () => {
    afterEach(async () => {
        await AsyncStorage.clear()
    })

    test.each<[string, readonly NavPin[], NavPin, boolean, readonly NavPin[]]>([
        ['pinning adds no slot while the slot is retired', ['replay'], 'errors', true, []],
        ['pinning a pinned list changes nothing', ['errors'], 'errors', true, ['errors']],
        ['unpinning empties the slot', ['errors'], 'errors', false, []],
    ])('%s', (_name, pins, pin, pinned, expected) => {
        expect(nextNavPins(pins, pin, pinned)).toEqual(expected)
    })

    test('names the list a new pin replaces, for the toast', () => {
        expect(replacedNavPin(['replay'], 'errors')).toBe('replay')
        expect(replacedNavPin(['errors'], 'errors')).toBeNull()
        expect(replacedNavPin([], 'errors')).toBeNull()
    })

    test('loads a saved list as no pins and leaves it on the device', async () => {
        const saved = JSON.stringify({ state: { pins: ['errors'] }, version: 0 })
        await AsyncStorage.setItem(STORAGE_KEY, saved)
        let store: NavPinModule['useNavPinStore'] | undefined
        jest.isolateModules(() => {
            store = jest.requireActual<NavPinModule>('./navPinStore').useNavPinStore
        })
        await waitFor(() => expect(store?.persist.hasHydrated()).toBe(true))

        expect(store?.getState().pins).toEqual([])
        expect(await AsyncStorage.getItem(STORAGE_KEY)).toBe(saved)
    })
})
