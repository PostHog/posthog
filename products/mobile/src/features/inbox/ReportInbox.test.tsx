import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import { getNetworkStateAsync, NetworkStateType } from 'expo-network'
import { AppState, FlatList } from 'react-native'

import { setAuthProvider } from '@/api/client'
import { useConnectivity } from '@/lib/connectivity'
import { inboxFromReports } from '@/model/adapters/inbox'
import { reportFixture } from '@/model/adapters/testFixtures'
import type { InboxItem } from '@/model/types'

import { reportDetailQuery, reportSignalsQuery } from '../report/queries'
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
jest.mock('expo-router', () => ({ useRouter: () => ({ setParams: jest.fn() }) }))
jest.mock('@/lib/analytics', () => ({ track: jest.fn() }))
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual('@/demo/demoMode'),
    useDataMode: () => mockDataMode,
}))
jest.mock('./hooks', () => ({
    useInboxItems: () => ({ data: mockItems, unfiltered: mockItems }),
    useSetReportRead: () => jest.fn(),
}))
jest.mock('./InboxRow', () => ({ InboxRow: () => null }))
jest.mock('./InboxFilterSheet', () => ({ InboxFilterSheet: () => null }))
jest.mock('./InboxRowActions', () => ({ InboxRowActions: () => null }))

const mockScope = { host: 'https://app.example.com', projectId: 2 }
let mockDataMode: 'live' | 'demo' = 'live'
const mockItems = inboxFromReports(Array.from({ length: 20 }, (_, index) => reportFixture({ id: `report-${index}` })))

function response(status: number, body: unknown): Response {
    return {
        ok: status < 400,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('ReportInbox', () => {
    const originalAppState = AppState.currentState
    beforeEach(() => {
        AppState.currentState = 'active'
        mockDataMode = 'live'
        useConnectivity.setState({ status: 'connected', type: NetworkStateType.WIFI })
        jest.mocked(getNetworkStateAsync).mockResolvedValue({ type: NetworkStateType.WIFI, isConnected: true })
    })

    afterEach(() => {
        AppState.currentState = originalAppState
        setAuthProvider(null)
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    test('prefetches visible reports only while the inbox is active', async () => {
        setAuthProvider({
            getAuth: () => ({ ...mockScope, accessToken: 'token', session: 1 }),
            refreshAccessToken: async () => null,
        })
        const fetch = jest.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
            const { pathname } = new URL(String(url))
            if (pathname.includes('/today/')) {
                return response(404, { detail: 'Not found' })
            }
            if (pathname.endsWith('/artefacts/')) {
                return response(200, { results: [], next: null, count: 0 })
            }
            if (pathname.endsWith('/signals/')) {
                return response(200, { signals: [] })
            }
            const id = pathname.match(/\/reports\/([^/]+)\/$/)?.[1]
            return response(200, reportFixture({ id }))
        })
        const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })
        const view = render(
            <QueryClientProvider client={client}>
                <ReportInbox selectedReportId="report-0" active={false} />
            </QueryClientProvider>
        )
        fireEvent(screen.UNSAFE_getByType(FlatList), 'viewableItemsChanged', {
            viewableItems: [{ item: mockItems[0], index: 0, key: mockItems[0]?.id, isViewable: true }],
            changed: [],
        })
        expect(fetch).not.toHaveBeenCalled()

        view.rerender(
            <QueryClientProvider client={client}>
                <ReportInbox selectedReportId="report-0" active />
            </QueryClientProvider>
        )
        await waitFor(() =>
            expect(client.getQueryData(reportDetailQuery(mockScope, 'report-0').queryKey)).toBeDefined()
        )
        await waitFor(() =>
            expect(client.getQueryData(reportDetailQuery(mockScope, 'report-1').queryKey)).toBeDefined()
        )

        const index = 15
        const item = mockItems[index]
        if (!item) {
            throw new Error('Missing visible report fixture')
        }
        const detailKey = reportDetailQuery(mockScope, item.reportId).queryKey
        expect(client.getQueryData(detailKey)).toBeUndefined()

        fireEvent(screen.UNSAFE_getByType(FlatList), 'viewableItemsChanged', {
            viewableItems: [{ item, index, key: item.id, isViewable: true }],
            changed: [],
        })

        await waitFor(() => expect(client.getQueryData(detailKey)).toMatchObject({ id: item.reportId }))
        await waitFor(() =>
            expect(client.getQueryData(reportSignalsQuery(mockScope, item.reportId).queryKey)).toEqual({ signals: [] })
        )
    })

    test.each(['measured', 'dragged', 'inactive', 'unmounted'] as const)(
        'handles a delayed selected-report reveal when %s',
        (state) => {
            jest.useFakeTimers()
            mockDataMode = 'demo'
            const scroll = jest.spyOn(FlatList.prototype, 'scrollToIndex').mockImplementationOnce(function (
                this: FlatList<InboxItem>,
                { index }
            ) {
                this.props.onScrollToIndexFailed?.({ index, averageItemLength: 100, highestMeasuredFrameIndex: 2 })
            })
            scroll.mockImplementation(() => undefined)
            const estimate = jest.spyOn(FlatList.prototype, 'scrollToOffset').mockImplementation(() => undefined)
            const client = new QueryClient()
            const view = render(
                <QueryClientProvider client={client}>
                    <ReportInbox selectedReportId="report-15" active />
                </QueryClientProvider>
            )
            const target = { index: 15, animated: false, viewPosition: 0.4 }
            expect(scroll).toHaveBeenCalledTimes(1)
            expect(scroll).toHaveBeenLastCalledWith(target)
            expect(estimate).toHaveBeenCalledWith({ offset: 1500, animated: false })

            fireEvent(screen.UNSAFE_getByType(FlatList), 'contentSizeChange', 300, 4000)
            if (state === 'dragged') fireEvent(screen.UNSAFE_getByType(FlatList), 'scrollBeginDrag')
            if (state === 'inactive') {
                view.rerender(
                    <QueryClientProvider client={client}>
                        <ReportInbox selectedReportId="report-15" active={false} />
                    </QueryClientProvider>
                )
            }
            if (state === 'unmounted') view.unmount()
            act(() => jest.advanceTimersByTime(64))
            expect(scroll).toHaveBeenCalledTimes(state === 'measured' ? 2 : 1)
            expect(scroll).toHaveBeenLastCalledWith(target)
        }
    )
})
