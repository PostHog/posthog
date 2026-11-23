import { act, renderHook } from '@testing-library/react-native'

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
        act(() => result.current.setPreference('mobile'))
        expect(result.current.preference).toBe('mobile')
        mockScope = { ...mockScope, projectId: 101 }
        rerender({})
        expect(result.current.preference).toBe('all')
        act(() => result.current.setPreference('web'))
        mockScope = { host: 'https://other.example.com', projectId: 100 }
        rerender({})
        expect(result.current.preference).toBe('all')
        mockScope = { host: 'https://example.com', projectId: 100 }
        rerender({})
        expect(result.current.preference).toBe('mobile')
        mockSession = 2
        rerender({})
        expect(result.current.preference).toBe('all')
    })
})
