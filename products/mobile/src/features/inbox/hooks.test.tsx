import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'

import { useMarkReadOnOpen } from './hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})

describe('useMarkReadOnOpen', () => {
    const posted: unknown[] = []

    beforeEach(() => {
        posted.length = 0
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2 }),
            refreshAccessToken: async () => null,
        })
        // Read posts never answer, so the first one is still in flight when the next report opens.
        globalThis.fetch = jest.fn((_url: string, init: RequestInit) => {
            posted.push(JSON.parse(String(init.body)))
            return new Promise<Response>(() => undefined)
        }) as unknown as typeof fetch
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test('marks each report read on a fast Prev/Next', async () => {
        const queryClient = new QueryClient()
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const { rerender } = renderHook(({ id }: { id: string }) => useMarkReadOnOpen(id), {
            initialProps: { id: 'report-1' },
            wrapper,
        })
        rerender({ id: 'report-2' })
        await act(async () => undefined)

        expect(posted).toEqual([
            { report_ids: ['report-1'], read: true },
            { report_ids: ['report-2'], read: true },
        ])
    })
})
