import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react-native'
import type { ReactElement, ReactNode } from 'react'

import { setAuthProvider } from '@/api/client'
import { fetchReport, reportKeys, type SignalReportApi } from '@/api/reports'
import { reportFixture } from '@/model/adapters/testFixtures'

import { useSetPriorityAction } from './hooks'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-notifications', () => ({}))
jest.mock('@/auth/useProjectScope', () => {
    const scope = { host: 'https://app.example.com', projectId: 2 }
    return { useProjectScope: () => scope }
})

const SCOPE = { host: 'https://app.example.com', projectId: 2 }
const REPORT_ID = 'report-1'
const REPORT_URL = `https://app.example.com/api/projects/2/signals/reports/${REPORT_ID}/`
const DETAIL_KEY = reportKeys.detail(SCOPE, REPORT_ID)

function jsonResponse(status: number, body: unknown): Response {
    return {
        ok: status < 400,
        status,
        headers: new Map(),
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('useSetPriorityAction', () => {
    afterEach(() => {
        setAuthProvider(null)
    })

    test('posts a priority judgment and resolves once the report carries the new priority', async () => {
        setAuthProvider({
            getAuth: () => ({ host: 'https://app.example.com', accessToken: 'token', projectId: 2, session: 1 }),
            refreshAccessToken: async () => null,
        })
        let serverPriority = 'P3'
        const fetchMock = jest.fn(async (_url: string, init: RequestInit) => {
            if (init.method === 'POST') {
                serverPriority = 'P0'
                return jsonResponse(201, { id: 'artefact-1', type: 'priority_judgment' })
            }
            return jsonResponse(200, reportFixture({ id: REPORT_ID, priority: serverPriority }))
        })
        globalThis.fetch = fetchMock as unknown as typeof fetch
        const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        const wrapper = ({ children }: { children: ReactNode }): ReactElement => (
            <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
        )
        const { result } = renderHook(
            () => ({
                report: useQuery({ queryKey: DETAIL_KEY, queryFn: ({ signal }) => fetchReport(REPORT_ID, signal) }),
                action: useSetPriorityAction(REPORT_ID),
            }),
            { wrapper }
        )
        await waitFor(() => expect(result.current.report.data?.priority).toBe('P3'))

        // The sheet closes when `run` resolves, so the cached report must already hold the new priority then.
        let priorityWhenDone: string | null | undefined
        await act(async () => {
            await result.current.action.run('P0')
            priorityWhenDone = queryClient.getQueryData<SignalReportApi>(DETAIL_KEY)?.priority
        })
        expect(priorityWhenDone).toBe('P0')

        const post = fetchMock.mock.calls.find(([, init]) => init.method === 'POST')
        expect(post?.[0]).toBe(`${REPORT_URL}artefacts/`)
        const body = JSON.parse(String(post?.[1].body))
        expect(body).toEqual({
            artefact_type: 'priority_judgment',
            content: { priority: 'P0', explanation: expect.stringMatching(/\S/) },
        })
    })
})
