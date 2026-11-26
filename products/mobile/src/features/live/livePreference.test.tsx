import AsyncStorage from '@react-native-async-storage/async-storage'
import { act, renderHook } from '@testing-library/react-native'

import type { AuthState } from '@/auth/authStore'
import { DEFAULT_LIVE_TRAFFIC_FILTERS } from '@/model/liveTrafficFilters'

import { normalizeLivePreference, useLivePreference, useLivePreferencesStore } from './livePreference'

let mockScope = { host: 'https://example.com', projectId: 100 }
let mockUser: AuthState['user'] = {
    uuid: 'first-user',
    distinctId: 'first-user',
    email: 'first@example.com',
    name: 'First User',
}
let mockMode: 'demo' | 'live' = 'live'
jest.mock('@/auth/authStore', () => ({
    useAuthStore: (select: (state: Pick<AuthState, 'user'>) => unknown) => select({ user: mockUser }),
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({ useDataMode: () => mockMode }))

describe('Live preferences', () => {
    it.each([undefined, 'auto', 'both', 'all', 'invalid'])(
        'normalizes legacy or missing selection %s to All',
        (value) => {
            expect(normalizeLivePreference(value)).toBe('all')
        }
    )

    it('restores the selected filters and banner visibility across app launches within the same project and account', async () => {
        const { result, rerender } = renderHook(() => useLivePreference())
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        expect(result.current.showFilterBanner).toBe(true)
        const filters = {
            ...DEFAULT_LIVE_TRAFFIC_FILTERS,
            excludeBots: true,
            hostname: 'first.example.com',
            pathPrefix: '/product',
            pathMode: 'exact' as const,
            countryCode: 'US',
            deviceType: 'Mobile',
            channelType: 'Organic Search',
            referringDomain: 'google.com',
        }
        act(() => result.current.setLiveFilters('mobile', filters))
        act(() => result.current.setShowFilterBanner(false))
        const storageKey = 'posthog-mobile-live-preferences'
        const saved = await AsyncStorage.getItem(storageKey)
        expect(saved).not.toBeNull()
        await act(async () => {
            useLivePreferencesStore.setState({ values: {} })
            await AsyncStorage.setItem(storageKey, saved ?? '')
            await useLivePreferencesStore.persist.rehydrate()
        })
        expect(result.current).toMatchObject({ preference: 'mobile', trafficFilters: filters, showFilterBanner: false })

        mockScope = { ...mockScope, projectId: 101 }
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        expect(result.current.showFilterBanner).toBe(true)
        act(() => result.current.setPreference('web'))
        mockScope = { host: 'https://other.example.com', projectId: 100 }
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        mockScope = { host: 'https://example.com', projectId: 100 }
        rerender({})
        expect(result.current.preference).toBe('mobile')
        expect(result.current.trafficFilters).toEqual(filters)
        const firstUser = mockUser
        mockUser = { uuid: 'second-user', distinctId: 'second-user', email: 'second@example.com', name: 'Second User' }
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        expect(result.current.showFilterBanner).toBe(true)
        mockUser = firstUser
        mockMode = 'demo'
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        expect(result.current.showFilterBanner).toBe(true)
    })
})
