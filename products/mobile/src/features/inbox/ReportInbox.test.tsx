import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native'
import { FlatList } from 'react-native'

import { setAuthProvider } from '@/api/client'
import { inboxFromReports } from '@/model/adapters/inbox'
import { reportFixture } from '@/model/adapters/testFixtures'

import { reportDetailQuery, reportSignalsQuery } from '../report/queries'
import { INITIAL_PREFETCH_COUNT } from './prefetchPlan'
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
    useDataMode: () => 'live',
}))
jest.mock('./hooks', () => ({
    useInboxItems: () => ({ data: mockItems, unfiltered: mockItems }),
    useSetReportRead: () => jest.fn(),
}))
jest.mock('./InboxRow', () => ({ InboxRow: () => null }))
jest.mock('./InboxFilterSheet', () => ({ InboxFilterSheet: () => null }))
jest.mock('./InboxRowActions', () => ({ InboxRowActions: () => null }))

const mockScope = { host: 'https://app.example.com', projectId: 2 }
const mockItems = inboxFromReports(
    Array.from({ length: INITIAL_PREFETCH_COUNT + 5 }, (_, index) => reportFixture({ id: `report-${index}` }))
)

function response(status: number, body: unknown): Response {
    return {
        ok: status < 400,
        status,
        headers: { get: () => null },
        text: async () => JSON.stringify(body),
    } as unknown as Response
}

describe('ReportInbox', () => {
    afterEach(() => {
        setAuthProvider(null)
        jest.restoreAllMocks()
    })

    test('warms the report cache when scrolling past the initial prefetch window', async () => {
        setAuthProvider({
            getAuth: () => ({ ...mockScope, accessToken: 'token', session: 1 }),
            refreshAccessToken: async () => null,
        })
        jest.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
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
        render(
            <QueryClientProvider client={client}>
                <ReportInbox selectedReportId="report-0" active />
            </QueryClientProvider>
        )
        await waitFor(() =>
            expect(
                client.getQueryData(reportDetailQuery(mockScope, `report-${INITIAL_PREFETCH_COUNT - 1}`).queryKey)
            ).toBeDefined()
        )

        const index = INITIAL_PREFETCH_COUNT + 4
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
})
