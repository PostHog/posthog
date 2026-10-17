import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { useViewsList } from './pinHooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-router', () => {
    const { useEffect } = jest.requireActual<typeof import('react')>('react')
    return {
        useFocusEffect: (effect: () => undefined | (() => void)) => useEffect(effect, [effect]),
        useIsFocused: () => true,
    }
})
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'demo',
}))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => null }))

let client = new QueryClient()

function wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

async function advance(ms: number): Promise<void> {
    await act(async () => {
        jest.advanceTimersByTime(ms)
    })
}

describe('views in demo mode', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    test('reads the pins, forces once when allowed, then explains the wait', async () => {
        const { result } = renderHook(() => useViewsList(), { wrapper })

        expect(result.current.pins.data?.map((pin) => [pin.kind, pin.ref, pin.display.mode])).toEqual([
            ['dashboard', 'demo-dash-kpis', 'number'],
            ['insight', 'demo-ins-signups', 'chart'],
            ['web_analytics', null, 'row'],
            ['notebook', 'demo-nb-launch', 'row'],
        ])
        expect(result.current.refresh.status.text).toBe('Updating…')

        await advance(1000)
        expect(result.current.refresh.status.text).toBe('Updated 42 min ago')
        // The first read was under a minute ago, and each item gets at most one request a minute.
        expect(result.current.refresh.button).toBe('blocked')

        await advance(60_000)
        expect(result.current.refresh.button).toBe('idle')
        act(() => result.current.refresh.onButton())
        await advance(1000)
        expect(result.current.refresh.status.text).toBe('Updated just now')
        expect(result.current.refresh.button).toBe('blocked')

        act(() => result.current.refresh.onButton())
        expect(result.current.refresh.hint).toBe('You can refresh again in 5 min.')
        await advance(3000)
        expect(result.current.refresh.hint).toBeNull()
    })
})
