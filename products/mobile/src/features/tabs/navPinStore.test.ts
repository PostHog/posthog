import AsyncStorage from '@react-native-async-storage/async-storage'
import { waitFor } from '@testing-library/react-native'

import { type NavPin, nextNavPins, replacedNavPin } from './navPinStore'

const STORAGE_KEY = 'nav-pins:v1'

type NavPinModule = typeof import('./navPinStore')

let mockMaxNavPins = 0
jest.mock('./navPinSlot', () => ({
    get MAX_NAV_PINS(): number {
        return mockMaxNavPins
    },
    get NAV_PINS_ENABLED(): boolean {
        return mockMaxNavPins > 0
    },
}))

describe('navPinStore', () => {
    afterEach(async () => {
        mockMaxNavPins = 0
        await AsyncStorage.clear()
    })

    test.each<[string, readonly NavPin[], NavPin, boolean, readonly NavPin[]]>([
        ['pinning adds no slot while the cap is 0', ['replay'], 'errors', true, []],
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

    test.each<[string, number, unknown[], NavPin[]]>([
        ['a saved list loads as no pins while the cap is 0', 0, ['errors'], []],
        ['a saved Live pin is dropped, because Live is Home', 1, ['live', 'errors'], ['errors']],
    ])('%s, and the saved list stays on the device', async (_name, cap, pins, expected) => {
        mockMaxNavPins = cap
        const saved = JSON.stringify({ state: { pins }, version: 0 })
        await AsyncStorage.setItem(STORAGE_KEY, saved)
        let store: NavPinModule['useNavPinStore'] | undefined
        jest.isolateModules(() => {
            store = jest.requireActual<NavPinModule>('./navPinStore').useNavPinStore
        })
        await waitFor(() => expect(store?.persist.hasHydrated()).toBe(true))

        expect(store?.getState().pins).toEqual(expected)
        expect(await AsyncStorage.getItem(STORAGE_KEY)).toBe(saved)
    })
})
