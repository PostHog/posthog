import { QueryClient } from '@tanstack/react-query'
import { waitFor } from '@testing-library/react-native'

import type { InsightBasicApi } from '@/api/insights'
import type { PaginatedApi } from '@/api/reports'
import type { FileSystemShortcutApi } from '@/api/shortcuts'
import { installAuthProvider, useAuthStore } from '@/auth/authStore'
import {
    type SessionIdentity,
    type SessionTokens,
    saveRefreshedTokens,
    sessionGeneration,
    setSessionTokens,
} from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { viewsKeys } from '@/features/views/viewsCache'

import { clearWidgetState, startChartWidgetSync, syncWidgetCatalog, syncWidgetCredentials } from './chartWidgetSync'

const mockSetCredentials = jest.fn()
const mockClearCredentials = jest.fn()
const mockSetCatalog = jest.fn()
jest.mock('../../../modules/chart-widget', () => ({
    isAvailable: () => true,
    setCredentials: (credentials: unknown) => mockSetCredentials(credentials),
    clearCredentials: () => mockClearCredentials(),
    setCatalog: (json: string) => mockSetCatalog(json),
    clearCatalog: () => undefined,
    reloadWidgets: () => undefined,
}))
jest.mock('expo-secure-store', () => {
    const items = new Map<string, string>()
    return {
        getItemAsync: async (key: string) => items.get(key) ?? null,
        setItemAsync: async (key: string, value: string) => {
            items.set(key, value)
        },
        deleteItemAsync: async (key: string) => {
            items.delete(key)
        },
    }
})

const HOST = 'https://us.posthog.com'
const USER = { uuid: 'user-1', distinctId: 'user-1', email: 'ada@example.com', name: 'Ada' }
const KEY: SessionTokens = {
    kind: 'personal_api_key',
    accessToken: 'phx_example_key',
    refreshToken: null,
    expiresAt: null,
    grantedScopes: null,
    requestedScopes: null,
}
const OAUTH: SessionTokens = {
    kind: 'oauth',
    accessToken: 'example-access',
    refreshToken: 'example-refresh',
    expiresAt: Date.now() + 3_600_000,
    grantedScopes: null,
    requestedScopes: null,
}

function owner(tokens: SessionTokens): SessionIdentity {
    return {
        host: HOST,
        clientId: tokens.kind === 'oauth' ? 'example-client' : null,
        method: tokens.kind,
        userUuid: USER.uuid,
    }
}

function signIn(tokens: SessionTokens): void {
    setSessionTokens(tokens, owner(tokens))
    useAuthStore.setState({
        status: 'signed_in',
        signedIn: true,
        host: HOST,
        clientId: owner(tokens).clientId,
        method: tokens.kind,
        user: USER,
        projects: [{ id: 2, name: 'Example project', organizationId: 'org-1', organizationName: 'Example org' }],
        projectId: 2,
        projectName: 'Example project',
    })
}

// No garbage collection timer, so Jest can exit when the tests finish.
function testClient(): QueryClient {
    return new QueryClient({ defaultOptions: { queries: { gcTime: Number.POSITIVE_INFINITY } } })
}

function shortcut(id: string, ref: string, type = 'insight'): FileSystemShortcutApi {
    return { id, path: `Pin ${id}`, type, ref, href: null, order: 0, created_at: '2026-10-01T10:00:00Z' }
}

function json(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('chart widget sync', () => {
    let stop: (() => void) | null = null

    beforeAll(async () => {
        await useDemoMode.persist.rehydrate()
    })

    const fetchMock = jest.fn<Promise<Response>, [string, RequestInit | undefined]>()

    beforeEach(() => {
        // A sync without a cached pin list prefetches it, so no test may reach the network.
        fetchMock.mockReset()
        fetchMock.mockResolvedValue(json(404, { detail: 'Not found.' }))
        globalThis.fetch = fetchMock as unknown as typeof fetch
        installAuthProvider()
        setSessionTokens(null)
        useAuthStore.setState({ status: 'signed_out', signedIn: false, user: null, projectId: null, projectName: null })
        useDemoMode.setState({ enabled: false })
        clearWidgetState()
        mockSetCredentials.mockClear()
        mockClearCredentials.mockClear()
        mockSetCatalog.mockClear()
    })

    afterEach(() => {
        stop?.()
        stop = null
    })

    it('writes the session once while it stays the same, and again when a refresh rotates the token', async () => {
        signIn(OAUTH)
        stop = startChartWidgetSync(testClient())

        useAuthStore.setState({ accountLoading: true })
        syncWidgetCredentials('launch')

        expect(mockSetCredentials).toHaveBeenCalledTimes(1)

        await saveRefreshedTokens({ ...OAUTH, accessToken: 'example-rotated' }, sessionGeneration())

        expect(mockSetCredentials).toHaveBeenCalledTimes(2)
        expect(mockSetCredentials).toHaveBeenLastCalledWith({
            host: HOST,
            projectId: 2,
            projectName: 'Example project',
            accessToken: 'example-rotated',
            expiresAt: OAUTH.expiresAt,
            userUuid: USER.uuid,
        })
    })

    it('clears the widget when the session ends, and writes again when the same account signs in', async () => {
        signIn(KEY)
        stop = startChartWidgetSync(testClient())

        await useAuthStore.getState().signOut()

        expect(mockClearCredentials).toHaveBeenCalled()
        expect(mockSetCredentials).toHaveBeenCalledTimes(1)

        signIn(KEY)

        expect(mockSetCredentials).toHaveBeenCalledTimes(2)
    })

    it('clears the widget when demo mode starts and writes nothing while it lasts, even with a session', async () => {
        signIn(OAUTH)
        stop = startChartWidgetSync(testClient())

        useDemoMode.setState({ enabled: true })
        await saveRefreshedTokens({ ...OAUTH, accessToken: 'example-rotated' }, sessionGeneration())

        expect(mockClearCredentials).toHaveBeenCalled()
        expect(mockSetCredentials).toHaveBeenCalledTimes(1)
    })

    it('writes the catalog from a complete pin list only, so pins past a cut list never vanish from the widget', async () => {
        signIn(KEY)
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        const metadata: InsightBasicApi = {
            id: 123,
            short_id: 'sig1',
            name: 'Signups',
            derived_name: null,
            query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode' }] } },
        }
        client.setQueryData(viewsKeys.pinMetadata(scope, 'sig1'), metadata)
        client.setQueryData<PaginatedApi<FileSystemShortcutApi>>(viewsKeys.shortcuts(scope), {
            count: 101,
            next: `${HOST}/api/projects/2/file_system_shortcut/?offset=100`,
            results: [shortcut('s-signups', 'sig1')],
        })
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)

        expect(mockSetCatalog).not.toHaveBeenCalled()

        client.setQueryData<PaginatedApi<FileSystemShortcutApi>>(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        await syncWidgetCatalog(client)

        expect(mockSetCatalog).toHaveBeenCalledTimes(1)
        expect(JSON.parse(mockSetCatalog.mock.calls[0][0])).toMatchObject({
            projectId: 2,
            pins: [{ id: 's-signups', insightId: 123, eligible: true }],
        })
    })

    it('reads the pin list itself after a sign in, so the widget has a catalog before Views opens', async () => {
        fetchMock.mockImplementation(async (url) =>
            url.includes('/api/projects/2/file_system_shortcut/')
                ? json(200, { count: 1, next: null, results: [shortcut('s-kpis', '12', 'dashboard')] })
                : json(404, { detail: 'Not found.' })
        )
        stop = startChartWidgetSync(testClient())

        signIn(KEY)

        await waitFor(() => expect(mockSetCatalog).toHaveBeenCalledTimes(1))
        expect(JSON.parse(mockSetCatalog.mock.calls[0][0])).toMatchObject({
            projectId: 2,
            pins: [{ id: 's-kpis', dashboardId: 12, eligible: false, reason: 'Choose a tile in Views first' }],
        })
    })
})
