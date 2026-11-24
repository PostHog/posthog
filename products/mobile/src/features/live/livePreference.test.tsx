import { act, renderHook } from '@testing-library/react-native'

import { DEFAULT_LIVE_TRAFFIC_FILTERS } from '@/model/liveTrafficFilters'

import { normalizeLivePreference, useLivePreference } from './livePreference'

let mockScope = { host: 'https://example.com', projectId: 100 }
let mockSession = 1
jest.mock('@/auth/authStore', () => ({ addSessionEndTask: jest.fn() }))
jest.mock('@/auth/tokens', () => ({ sessionGeneration: () => mockSession }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))

describe('Live preferences', () => {
    it.each([undefined, 'auto', 'both', 'all', 'invalid'])(
        'normalizes legacy or missing selection %s to All',
        (value) => {
            expect(normalizeLivePreference(value)).toBe('all')
        }
    )

    it('defaults to All and isolates choices across project, host, and account session', () => {
        const { result, rerender } = renderHook(() => useLivePreference())
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
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
        expect(result.current.preference).toBe('mobile')
        expect(result.current.trafficFilters).toEqual(filters)
        mockScope = { ...mockScope, projectId: 101 }
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        act(() => result.current.setPreference('web'))
        mockScope = { host: 'https://other.example.com', projectId: 100 }
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
        mockScope = { host: 'https://example.com', projectId: 100 }
        rerender({})
        expect(result.current.preference).toBe('mobile')
        expect(result.current.trafficFilters).toEqual(filters)
        mockSession = 2
        rerender({})
        expect(result.current.preference).toBe('all')
        expect(result.current.trafficFilters).toEqual(DEFAULT_LIVE_TRAFFIC_FILTERS)
    })
})
