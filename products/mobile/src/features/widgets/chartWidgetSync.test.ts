import { QueryClient } from '@tanstack/react-query'
import { waitFor } from '@testing-library/react-native'
import { resetBudgets, trySpend } from '@/api/budget'
import { ApiError, apiJson } from '@/api/client'
import type { InsightApi, InsightBasicApi } from '@/api/insights'
import { queryClient } from '@/api/queryClient'
import type { PaginatedApi } from '@/api/reports'
import type { FileSystemShortcutApi } from '@/api/shortcuts'
import { addSessionEndTask, installAuthProvider, useAuthStore } from '@/auth/authStore'
import {
    type SessionIdentity,
    type SessionTokens,
    saveRefreshedTokens,
    sessionGeneration,
    setSessionTokens,
} from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { usePinPrefs } from '@/features/views/pinPrefsStore'
import { viewsQueue } from '@/features/views/refreshQueue'
import { useScopeErrorStore } from '@/features/views/useViewsAccess'
import { useItemErrors, viewsKeys } from '@/features/views/viewsCache'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'

import { clearWidgetState, startChartWidgetSync, syncWidgetCatalog, syncWidgetCredentials } from './chartWidgetSync'

const mockWidgetState = jest.fn()
const mockSetCredentials = jest.fn()
const mockClearCredentials = jest.fn()
const mockSetCatalog = jest.fn()
jest.mock('../../../modules/chart-widget', () => ({
    isAvailable: () => true,
    getWidgetState: () => mockWidgetState(),
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
        queryClient.setQueryDefaults(['views'], { gcTime: Number.POSITIVE_INFINITY })
        await useDemoMode.persist.rehydrate()
    })

    const fetchMock = jest.fn<Promise<Response>, [string, RequestInit | undefined]>()

    beforeEach(() => {
        // A sync without a cached pin list prefetches it, so no test may reach the network.
        viewsQueue.reset()
        useItemErrors.getState().reset()
        useScopeErrorStore.getState().clear()
        mockWidgetState.mockResolvedValue({
            installed: true,
            pinIds: ['s-signups', 's-kpis', 'a', 'b'],
            usesDefault: false,
        })
        resetBudgets()
        fetchMock.mockReset()
        fetchMock.mockResolvedValue(json(404, { detail: 'Not found.' }))
        globalThis.fetch = fetchMock as unknown as typeof fetch
        installAuthProvider()
        setSessionTokens(null)
        useAuthStore.setState({ status: 'signed_out', signedIn: false, user: null, projectId: null, projectName: null })
        useDemoMode.setState({ enabled: false })
        usePinPrefs.getState().clear()
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
        const client = testClient()
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)

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
        const client = testClient()
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)

        await useAuthStore.getState().signOut()

        expect(mockClearCredentials).toHaveBeenCalled()
        expect(mockSetCredentials).toHaveBeenCalledTimes(1)

        signIn(KEY)

        await syncWidgetCatalog(client)
        expect(mockSetCredentials).toHaveBeenCalledTimes(2)
    })

    it.each([USER.uuid, 'user-2'])('keeps an ended widget session retired while signing in %s', async (userUuid) => {
        signIn(KEY)
        const client = queryClient
        client.clear()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        client.setQueryData(
            viewsKeys.insight(scope, 'sig1', null, '-'),
            insightSnapshot(
                {
                    id: 123,
                    short_id: 'sig1',
                    name: 'Example',
                    query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery' }, display: 'BoldNumber' },
                    result: [[42]],
                    columns: ['value'],
                    types: [['value', 'UInt64']],
                } as unknown as InsightApi,
                undefined,
                { readAt: Date.now(), serverNow: Date.now() }
            )
        )
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].snapshot.valueText).toBe('42')
        let finishCleanup!: () => void
        let reachedCleanup!: () => void
        const cleanupStarted = new Promise<void>((resolve) => {
            reachedCleanup = resolve
        })
        const removeCleanup = addSessionEndTask(
            () =>
                new Promise<void>((resolve) => {
                    finishCleanup = resolve
                    reachedCleanup()
                })
        )
        fetchMock.mockImplementation(async (url) =>
            url.endsWith('/api/users/@me/')
                ? json(200, {
                      id: 2,
                      uuid: userUuid,
                      distinct_id: userUuid,
                      email: 'person@example.com',
                      first_name: 'Example',
                      last_name: '',
                      team: { id: 2, name: 'Example project' },
                      organization: { id: 'org-1', name: 'Example org', teams: [{ id: 2, name: 'Example project' }] },
                      organizations: [],
                  })
                : json(404, {})
        )
        const signingIn = useAuthStore.getState().signInWithPersonalApiKey(HOST, 'phx_example_replacement')
        try {
            await cleanupStarted
            mockSetCredentials.mockClear()
            mockSetCatalog.mockClear()
            // The account commit is paused, so cleanup subscribers and a foreground sync still see the old auth state.
            await syncWidgetCatalog(client)
            syncWidgetCredentials('launch')
            expect(mockSetCredentials).not.toHaveBeenCalled()
            expect(mockSetCatalog).not.toHaveBeenCalled()
            finishCleanup()
            await signingIn
            await syncWidgetCatalog(client)
            expect(mockSetCredentials).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    userUuid,
                    accessToken: 'phx_example_replacement',
                    projectId: 2,
                })
            )
            expect(mockSetCatalog).not.toHaveBeenCalled()
        } finally {
            finishCleanup()
            await signingIn
            removeCleanup()
            stop?.()
            stop = null
            await client.cancelQueries()
            client.clear()
        }
    })

    it('clears the widget when demo mode starts and writes nothing while it lasts, even with a session', async () => {
        signIn(OAUTH)
        const client = testClient()
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)

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
        const client = testClient()
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)

        signIn(KEY)

        await waitFor(() => expect(mockSetCatalog).toHaveBeenCalledTimes(1))
        expect(JSON.parse(mockSetCatalog.mock.calls[0][0])).toMatchObject({
            projectId: 2,
            pins: [{ id: 's-kpis', dashboardId: 12, eligible: false, reason: 'Choose a tile in Views first' }],
        })
    })
    it('offers an insight after opening it recovers a failed metadata read', async () => {
        signIn(KEY)
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        stop = startChartWidgetSync(client)
        await waitFor(() => expect(mockSetCatalog).toHaveBeenCalled())
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].eligible).toBe(false)
        const response: InsightApi = {
            id: 123,
            short_id: 'sig1',
            name: 'Signups',
            derived_name: null,
            query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode' }] } },
            result: [],
            last_refresh: null,
            cache_target_age: null,
            next_allowed_client_refresh: null,
        }
        client.setQueryData(
            viewsKeys.insight(scope, 'sig1', null, '-'),
            insightSnapshot(response, undefined, { readAt: Date.now(), serverNow: Date.now() })
        )
        await waitFor(() =>
            expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0]).toMatchObject({
                eligible: true,
                insightId: 123,
            })
        )
    })

    it('uses the newer opened insight instead of an older unsupported metadata response', async () => {
        signIn(KEY)
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        client.setQueryData(
            viewsKeys.pinMetadata(scope, 'sig1'),
            {
                id: 123,
                short_id: 'sig1',
                name: 'Signups',
                query: { kind: 'FunnelsQuery' },
            },
            { updatedAt: Date.now() - 1000 }
        )
        const response: InsightApi = {
            id: 123,
            short_id: 'sig1',
            name: 'Signups',
            derived_name: null,
            query: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode' }] },
            result: [],
            last_refresh: null,
            cache_target_age: null,
            next_allowed_client_refresh: null,
        }
        client.setQueryData(
            viewsKeys.insight(scope, 'sig1', null, '-'),
            insightSnapshot(response, undefined, { readAt: Date.now(), serverNow: Date.now() })
        )
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].eligible).toBe(true)
    })

    it.each([true, false])('selects a dashboard tile before selection, with a placed widget: %s', async (installed) => {
        signIn(KEY)
        mockWidgetState.mockResolvedValue({ installed, pinIds: [], usesDefault: false })
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-kpis', '12', 'dashboard')],
        })
        fetchMock.mockImplementation(async (url) =>
            url.includes('/dashboards/12/')
                ? json(200, {
                      id: 12,
                      name: 'Product KPIs',
                      tiles: [
                          {
                              id: 3,
                              insight: {
                                  id: 456,
                                  short_id: 'dau1',
                                  name: 'Daily active users',
                                  query: {
                                      kind: 'InsightVizNode',
                                      source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode' }] },
                                  },
                                  result: [],
                                  last_refresh: null,
                              },
                          },
                      ],
                  })
                : json(404, {})
        )
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0]).toMatchObject({
            id: 's-kpis',
            dashboardId: 12,
            insightId: 456,
            shortId: 'dau1',
            eligible: true,
        })
        expect(usePinPrefs.getState().projects).toEqual({})
    })

    it('uses cached automatic dashboard choices while preserving an explicit choice', async () => {
        signIn(KEY)
        mockWidgetState.mockResolvedValue({ installed: false, pinIds: [], usesDefault: false })
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-kpis', '12', 'dashboard')],
        })
        for (const [shortId, id] of [
            ['auto', 456],
            ['manual', 789],
        ] as const) {
            client.setQueryData(viewsKeys.pinMetadata(scope, shortId), {
                id,
                short_id: shortId,
                query: { kind: 'TrendsQuery' },
            })
        }
        client.setQueryData(viewsKeys.smartPinDisplays(scope, 'views-list'), {
            's-kpis': { mode: 'chart', tileId: 3, insightId: 456, insightShortId: 'auto' },
        })
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0]).toMatchObject({
            eligible: true,
            insightId: 456,
        })
        usePinPrefs.getState().setDisplay(`${HOST}|2`, 's-kpis', {
            mode: 'chart',
            tileId: 4,
            insightId: 789,
            insightShortId: 'manual',
        })
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].insightId).toBe(789)
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it('publishes selected data and cache updates while another metadata read is pending', async () => {
        signIn(KEY)
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 2,
            next: null,
            results: [shortcut('s-signups', 'sig1'), shortcut('unread', 'pending')],
        })
        const response = {
            id: 123,
            short_id: 'sig1',
            name: 'Signups',
            query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery' }, display: 'BoldNumber' },
            result: [[42]],
            columns: ['value'],
            types: [['value', 'UInt64']],
        } as unknown as InsightApi
        const update = (value: number): void => {
            client.setQueryData(
                viewsKeys.insight(scope, 'sig1', null, '-'),
                insightSnapshot({ ...response, result: [[value]] }, undefined, {
                    readAt: Date.now(),
                    serverNow: Date.now(),
                })
            )
        }
        update(42)
        let finishRead!: (value: Response) => void
        fetchMock.mockImplementation(
            () =>
                new Promise((resolve) => {
                    finishRead = resolve
                })
        )
        stop = startChartWidgetSync(client)
        await waitFor(() => expect(fetchMock).toHaveBeenCalled())
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0]).toMatchObject({
            snapshot: expect.objectContaining({ valueText: '42' }),
        })
        update(84)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].snapshot.valueText).toBe('84')
        client.setQueryData(
            viewsKeys.insight(scope, 'pending', null, '-'),
            insightSnapshot({ ...response, short_id: 'pending', result: [[88]] }, undefined, {
                readAt: Date.now() + 1,
                serverNow: Date.now(),
            })
        )
        finishRead(json(200, { id: 456, short_id: 'pending', query: { kind: 'unsupported' } }))
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[1].eligible).toBe(true)
    })

    it('prefetches the new project after the project-switch query reset', async () => {
        signIn(KEY)
        const client = testClient()
        client.setQueryData(viewsKeys.shortcuts({ host: HOST, projectId: 2 }), { count: 0, next: null, results: [] })
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)
        fetchMock.mockImplementation(async (url) =>
            url.includes('/api/projects/3/file_system_shortcut/')
                ? json(200, { count: 0, next: null, results: [] })
                : json(404, {})
        )
        useAuthStore.setState({ projectId: 3, projectName: 'Second project' })
        await client.resetQueries()
        await waitFor(() => expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').projectId).toBe(3))
    })
    it('does not keep the next project waiting on an old insight rate-limit pause', async () => {
        signIn(KEY)
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        viewsQueue.notePause('insights', new ApiError(429, {}, new Headers({ 'Retry-After': '60' })))
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        client.setQueryData(viewsKeys.shortcuts({ host: HOST, projectId: 3 }), { count: 0, next: null, results: [] })
        stop = startChartWidgetSync(client)
        await Promise.resolve()
        expect(mockSetCatalog).not.toHaveBeenCalled()

        useAuthStore.setState({ projectId: 3, projectName: 'Second project' })
        await syncWidgetCatalog(client)

        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').projectId).toBe(3)
        expect(fetchMock).not.toHaveBeenCalled()
    })
    it('paces background metadata and leaves capacity for a foreground read', async () => {
        jest.useFakeTimers()
        try {
            signIn(KEY)
            const client = testClient()
            client.setQueryData(viewsKeys.shortcuts({ host: HOST, projectId: 2 }), {
                count: 2,
                next: null,
                results: [shortcut('a', 'a'), shortcut('b', 'b')],
            })
            for (let i = 0; i < 29; i++) expect(trySpend('insights')).toBe(true)
            fetchMock.mockImplementation(async () =>
                json(200, {
                    id: 123,
                    short_id: 'a',
                    query: { kind: 'TrendsQuery', series: [] },
                    result: [],
                })
            )
            stop = startChartWidgetSync(client)
            await jest.advanceTimersByTimeAsync(0)
            expect(fetchMock).toHaveBeenCalledTimes(1)
            await apiJson('/api/projects/2/insights/foreground/')
            expect(fetchMock).toHaveBeenCalledTimes(2)
            await jest.advanceTimersByTimeAsync(999)
            expect(fetchMock).toHaveBeenCalledTimes(2)
            await jest.advanceTimersByTimeAsync(1001)
            expect(fetchMock).toHaveBeenCalledTimes(3)
            await syncWidgetCatalog(client)
        } finally {
            stop?.()
            await jest.advanceTimersByTimeAsync(0)
            jest.useRealTimers()
        }
    })
    it('keeps picker metadata but sends no credentials, results or background reads without a placed widget', async () => {
        signIn(KEY)
        mockWidgetState.mockResolvedValue({ installed: false, pinIds: [], usesDefault: false })
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        client.setQueryData(viewsKeys.pinMetadata(scope, 'sig1'), {
            id: 123,
            short_id: 'sig1',
            query: { kind: 'TrendsQuery' },
        })
        client.setQueryData(
            viewsKeys.insight(scope, 'sig1', null, '-'),
            insightSnapshot(
                {
                    id: 123,
                    short_id: 'sig1',
                    name: 'Example',
                    query: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery' }, display: 'BoldNumber' },
                    result: [[42]],
                    columns: ['value'],
                    types: [['value', 'UInt64']],
                } as unknown as InsightApi,
                undefined,
                { readAt: Date.now(), serverNow: Date.now() }
            )
        )
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)
        expect(fetchMock).not.toHaveBeenCalled()
        expect(mockSetCredentials).not.toHaveBeenCalled()
        expect(mockClearCredentials).toHaveBeenCalled()
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0]).toMatchObject({
            id: 's-signups',
            eligible: true,
        })
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].snapshot).toBeUndefined()
    })

    it('removes cached values from a pin that loses access', async () => {
        signIn(KEY)
        const client = testClient()
        const scope = { host: HOST, projectId: 2 }
        const key = viewsKeys.insight(scope, 'sig1', null, '-')
        client.setQueryData(viewsKeys.shortcuts(scope), {
            count: 1,
            next: null,
            results: [shortcut('s-signups', 'sig1')],
        })
        client.setQueryData(
            key,
            insightSnapshot(
                {
                    id: 123,
                    short_id: 'sig1',
                    name: 'Signups',
                    query: { kind: 'TrendsQuery' },
                    result: [],
                } as unknown as InsightApi,
                undefined,
                { readAt: Date.now(), serverNow: Date.now() }
            )
        )
        stop = startChartWidgetSync(client)
        await syncWidgetCatalog(client)
        useItemErrors.getState().set(JSON.stringify(key), 'no_access')
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0]).toMatchObject({ eligible: false })
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').pins[0].snapshot).toBeUndefined()
    })
    it('lets a new project sync while the old placement check is pending', async () => {
        signIn(KEY)
        const client = testClient()
        for (const projectId of [2, 3]) {
            client.setQueryData(viewsKeys.shortcuts({ host: HOST, projectId }), { count: 0, next: null, results: [] })
        }
        mockWidgetState.mockImplementationOnce(() => new Promise(() => undefined))
        stop = startChartWidgetSync(client)
        await waitFor(() => expect(mockWidgetState).toHaveBeenCalled())
        useAuthStore.setState({ projectId: 3, projectName: 'Second project' })
        await syncWidgetCatalog(client)
        expect(JSON.parse(mockSetCatalog.mock.calls.at(-1)?.[0] ?? '{}').projectId).toBe(3)
    })
})
