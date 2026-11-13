import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react-native'

import type { InsightApi } from '@/api/insights'
import { inboxCacheKey } from '@/api/readCacheKeys'
import type { ProjectScope } from '@/api/reports'
import type { FileSystemShortcutApi } from '@/api/shortcuts'
import { insightQueryKey } from '@/features/views/items'
import { usePinPrefs } from '@/features/views/pinPrefsStore'
import type { ViewsContext } from '@/features/views/useViewsContext'
import { viewsKeys } from '@/features/views/viewsCache'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'

import { LiveMeanwhile } from './LiveMeanwhile'

jest.mock('@react-native-async-storage/async-storage', () =>
    require('@react-native-async-storage/async-storage/jest/async-storage-mock')
)
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn(), navigate: jest.fn() }) }))
jest.mock('@/demo/demoMode', () => ({
    ...jest.requireActual<typeof import('@/demo/demoMode')>('@/demo/demoMode'),
    useDataMode: () => 'live',
}))
const mockScope: ProjectScope = { host: 'https://posthog.example.com', projectId: 7 }
let mockContext: ViewsContext | null = null
jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => mockScope }))
jest.mock('@/features/views/useViewsContext', () => ({ useViewsContext: () => mockContext }))

const shortcut: FileSystemShortcutApi = {
    id: 'shortcut-1',
    path: 'Daily signups',
    type: 'insight',
    ref: 'signups',
    href: '/insights/signups',
    order: 0,
    created_at: '2026-10-01T00:00:00Z',
}
const insight: InsightApi = {
    id: 7,
    short_id: 'signups',
    name: 'Daily signups',
    derived_name: null,
    query: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            interval: 'day',
            series: [{ kind: 'EventsNode', event: 'signed_up' }],
            trendsFilter: { display: 'BoldNumber' },
            dateRange: { date_from: '-7d' },
        },
    },
    result: [{ data: [10, 12, 14], days: ['2026-10-18', '2026-10-19', '2026-10-20'], label: 'signed_up' }],
    last_refresh: '2026-10-20T11:55:00Z',
    cache_target_age: '2026-10-20T12:55:00Z',
    next_allowed_client_refresh: '2026-10-20T12:00:00Z',
    is_cached: true,
    resolved_date_range: { date_from: '2026-10-18T00:00:00Z', date_to: '2026-10-20T23:59:59Z' },
}

describe('LiveMeanwhile', () => {
    const originalFetch = globalThis.fetch

    afterEach(() => {
        globalThis.fetch = originalFetch
    })

    test('shows the cached pin value and unread count without sending a request', () => {
        const fetch = jest.fn()
        globalThis.fetch = fetch as unknown as typeof globalThis.fetch
        const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
        client.setQueryData(viewsKeys.shortcuts(mockScope), { count: 1, next: null, results: [shortcut] })
        const snapshot = insightSnapshot(insight, undefined, { readAt: Date.now(), serverNow: Date.now() })
        client.setQueryData(
            insightQueryKey(mockScope, { shortId: 'signups', dashboardRef: null, override: null }),
            snapshot
        )
        client.setQueryData(inboxCacheKey(mockScope), { items: [], sourceUpdatedAt: Date.now() })
        usePinPrefs.getState().setDisplay(`${mockScope.host}|${mockScope.projectId}`, 'shortcut-1', { mode: 'number' })
        mockContext = {
            identity: 'live',
            mode: 'live',
            offline: false,
            scope: mockScope,
            dataScope: `${mockScope.host}|${mockScope.projectId}`,
            access: { state: 'ok' } as ViewsContext['access'],
            ready: true,
            item: { client, scope: mockScope, demo: false },
        }

        const screen = render(
            <QueryClientProvider client={client}>
                <LiveMeanwhile />
            </QueryClientProvider>
        )
        expect(screen.getByTestId('live-meanwhile-value-signups').props.children).toBe('14')
        expect(screen.getByText('Nothing unread')).toBeTruthy()
        expect(fetch).not.toHaveBeenCalled()
        screen.unmount()
        client.clear()
    })
})
