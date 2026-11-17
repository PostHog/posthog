import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import { AppState, RefreshControl } from 'react-native'

import { setAuthProvider } from '@/api/client'
import type { InboxStatusApi } from '@/api/inboxStatus'
import { reportKeys } from '@/api/reports'
import { useConnectivity } from '@/lib/connectivity'
import { reportFixture } from '@/model/adapters/testFixtures'

import { ReportInbox } from './ReportInbox'

jest.mock('react-native-worklets', () => jest.requireActual('react-native-worklets/src/mock'))
jest.mock('react-native-reanimated', () => ({
    ...jest.requireActual('react-native-reanimated/mock'),
    useReducedMotion: () => true,
}))
jest.mock(
    'react-native-safe-area-context',
    () => jest.requireActual('react-native-safe-area-context/jest/mock').default
)
jest.mock('react-native-keyboard-controller', () => jest.requireActual('react-native-keyboard-controller/jest'))
jest.mock('expo-notifications', () => ({}))
jest.mock('expo-router', () => ({ useRouter: () => ({ setParams: jest.fn() }), useIsFocused: () => true }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))

const mockScope = { host: 'https://app.example.com', projectId: 2 }

function jsonResponse(body: unknown): Response {
    return {
        ok: true,
        status: 200,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('report inbox setup refresh', () => {
    const originalAppState = AppState.currentState
    let client: QueryClient
    let status: InboxStatusApi
    let reports: ReturnType<typeof reportFixture>[]

    beforeEach(() => {
        jest.useFakeTimers()
        AppState.currentState = 'active'
        useConnectivity.setState({ status: 'connected' })
        client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity, retry: false } } })
        status = {
            setup_state: 'active',
            has_report_history: false,
            first_report_status: 'running',
            can_configure: true,
        }
        reports = []
        setAuthProvider({
            getAuth: () => ({ ...mockScope, accessToken: 'test-token', session: 1 }),
            refreshAccessToken: async () => null,
        })
        jest.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
            const path = new URL(String(url)).pathname
            if (path.endsWith('/inbox_status/')) return jsonResponse(status)
            if (path.endsWith('/reports/')) return jsonResponse({ results: reports, count: reports.length, next: null })
            if (path.endsWith('/read_state/')) return jsonResponse({ states: {} })
            throw new Error(`Unexpected request: ${path}`)
        })
    })

    afterEach(() => {
        client.clear()
        setAuthProvider(null)
        AppState.currentState = originalAppState
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test.each([
        { has_report_history: true, first_report_status: null },
        { has_report_history: false, first_report_status: 'report_created' },
    ] as const)('shows the first report when status polling detects %j', async (completed) => {
        const otherScope = { ...mockScope, projectId: 3 }
        client.setQueryData(reportKeys.inbox(otherScope), [])
        const view = render(
            <QueryClientProvider client={client}>
                <ReportInbox selectedReportId="previous-report" active />
            </QueryClientProvider>
        )
        await waitFor(() => expect(screen.getByText('Looking for your first report')).toBeTruthy())

        reports = [reportFixture({ id: 'first-report', title: 'An example finding' })]
        status = { ...status, ...completed }
        await act(async () => jest.advanceTimersByTimeAsync(15_000))
        await waitFor(() => expect(screen.getByText('An example finding')).toBeTruthy())
        expect(screen.queryByText('Nothing needs you right now')).toBeNull()
        expect(client.getQueryState(reportKeys.inbox(otherScope))?.isInvalidated).toBe(false)
        view.unmount()
    })

    test('pulling to refresh updates setup changed on another device', async () => {
        status = { ...status, setup_state: 'paused', first_report_status: null }
        const view = render(
            <QueryClientProvider client={client}>
                <ReportInbox selectedReportId="previous-report" active />
            </QueryClientProvider>
        )
        await waitFor(() => expect(screen.getByText('Self-driving is paused')).toBeTruthy())

        status = { ...status, setup_state: 'active' }
        fireEvent(screen.UNSAFE_getByType(RefreshControl), 'refresh')
        await waitFor(() => expect(screen.getByText('Waiting for your first report')).toBeTruthy())
        expect(screen.queryByText('Self-driving is paused')).toBeNull()
        view.unmount()
    })
})
