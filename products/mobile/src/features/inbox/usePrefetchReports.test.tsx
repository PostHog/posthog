import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import { inboxFromReports } from '@/model/adapters/inbox'
import { reportFixture } from '@/model/adapters/testFixtures'

import { usePrefetchReports } from './usePrefetchReports'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))

function response(status: number, body: unknown): Response {
    return {
        ok: status < 400,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('usePrefetchReports', () => {
    afterEach(() => {
        setAuthProvider(null)
    })

    test('asks once for a Today page the project does not have, not again when the window moves', async () => {
        const paths: string[] = []
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        globalThis.fetch = jest.fn(async (url: string) => {
            const { pathname } = new URL(url)
            paths.push(pathname)
            if (pathname.includes('/today/')) {
                return response(404, { detail: 'Not found' })
            }
            if (pathname.endsWith('/artefacts/')) {
                return response(200, { results: [], next: null, count: 0 })
            }
            if (pathname.endsWith('/signals/')) {
                return response(200, { signals: [] })
            }
            return response(200, reportFixture())
        }) as unknown as typeof fetch
        const items = (ids: string[]) => inboxFromReports(ids.map((id) => reportFixture({ id })))
        const queryClient = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const signalsOf = (id: string) => paths.filter((path) => path.endsWith(`/reports/${id}/signals/`))
        const { rerender } = renderHook(({ ids }: { ids: string[] }) => usePrefetchReports(items(ids)), {
            initialProps: { ids: ['a', 'b'] },
            wrapper,
        })
        await waitFor(() => expect(signalsOf('b')).toHaveLength(1))

        // A new row queues the whole window again, and `c` runs after `a` and `b`.
        rerender({ ids: ['a', 'b', 'c'] })
        await waitFor(() => expect(signalsOf('c')).toHaveLength(1))

        expect(paths.filter((path) => path.includes('/today/'))).toEqual([
            '/api/projects/2/today/reports/a/page/',
            '/api/projects/2/today/reports/b/page/',
            '/api/projects/2/today/reports/c/page/',
        ])
    })
})
