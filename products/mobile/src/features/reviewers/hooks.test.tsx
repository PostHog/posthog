import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'

import { useSetReviewersAction } from './hooks'

jest.mock('@/auth/useProjectScope', () => ({
    useProjectScope: () => ({ host: 'https://app.example.com', projectId: 2 }),
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

describe('useSetReviewersAction', () => {
    beforeEach(() => {
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
    })

    afterEach(() => {
        setAuthProvider(null)
    })

    test('preserves a GitHub-only reviewer from an older artefact page in the replacement PUT', async () => {
        const requests: { url: string; body: unknown }[] = []
        globalThis.fetch = jest.fn(async (input: string, init: RequestInit) => {
            const url = String(input)
            requests.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
            const response =
                init.method === 'PUT'
                    ? { id: 'new-assignment', type: 'suggested_reviewers', content: [] }
                    : url.includes('offset=100')
                      ? {
                            count: 101,
                            next: null,
                            results: [
                                {
                                    id: 'old-assignment',
                                    type: 'suggested_reviewers',
                                    content: [{ user_uuid: null, github_login: 'reviewer-on-github' }],
                                },
                            ],
                        }
                      : {
                            count: 101,
                            next: 'https://app.example.com/api/projects/2/signals/reports/report-1/artefacts/?limit=100&offset=100',
                            results: Array.from({ length: 100 }, (_, index) => ({
                                id: `newer-${index}`,
                                type: 'note',
                            })),
                        }
            return {
                ok: true,
                status: 200,
                headers: { get: () => null },
                text: async () => JSON.stringify(response),
            } as unknown as Response
        }) as unknown as typeof fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const { result, unmount } = renderHook(() => useSetReviewersAction('report-1'), { wrapper })
        try {
            await act(async () => {
                await result.current.run(['selected-user'])
            })
            expect(requests.map(({ url }) => new URL(url).searchParams.get('offset'))).toEqual([null, '100', null])
            expect(requests[2]?.body).toEqual({
                content: [{ user_uuid: 'selected-user' }, { github_login: 'reviewer-on-github' }],
            })
        } finally {
            unmount()
            client.clear()
        }
    })

    test('does not replace reviewers when an older artefact page fails to load', async () => {
        const methods: string[] = []
        globalThis.fetch = jest.fn(async (_input: string, init: RequestInit) => {
            methods.push(init.method ?? 'GET')
            const response =
                methods.length === 1
                    ? {
                          ok: true,
                          status: 200,
                          count: 101,
                          next: 'https://app.example.com/api/projects/2/signals/reports/report-1/artefacts/?limit=100&offset=100',
                          results: Array.from({ length: 100 }, (_, index) => ({ id: `newer-${index}`, type: 'note' })),
                      }
                    : { ok: false, status: 503, detail: 'Could not load artefacts' }
            return {
                ok: response.ok,
                status: response.status,
                headers: { get: () => null },
                text: async () => JSON.stringify(response),
            } as unknown as Response
        }) as unknown as typeof fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={client}>{children}</QueryClientProvider>
        )
        const { result, unmount } = renderHook(() => useSetReviewersAction('report-1'), { wrapper })
        try {
            await act(async () => {
                await expect(result.current.run(['selected-user'])).rejects.toThrow('Could not load artefacts')
            })
            expect(methods).toEqual(['GET', 'GET'])
        } finally {
            unmount()
            client.clear()
        }
    })
})
