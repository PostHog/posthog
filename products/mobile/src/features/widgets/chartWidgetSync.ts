import type { QueryClient, QueryKey } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { fetchInsightMetadata, type InsightBasicApi } from '@/api/insights'
import type { PaginatedApi, ProjectScope } from '@/api/reports'
import { type FileSystemShortcutApi, isCompleteShortcutPage } from '@/api/shortcuts'
import { type AuthState, addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionIdentity, getSessionTokens, onSessionTokensChanged, sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { READ_FLOOR_MS } from '@/features/views/freshness'
import { listRead, readShortcuts, retryListRead } from '@/features/views/listReads'
import { NO_PIN_PREFS, usePinPrefs } from '@/features/views/pinPrefsStore'
import { discoverPinDisplays } from '@/features/views/useSmartPinDisplays'
import { featureAccessFor, useScopeErrorStore } from '@/features/views/useViewsAccess'
import { overrideKey, viewsKeys } from '@/features/views/viewsCache'
import { abortError } from '@/lib/abort'
import { track } from '@/lib/analytics'
import { pinsFromShortcuts } from '@/model/adapters/viewPins'
import type { InsightSnapshot, PinView } from '@/model/views'

// Local Expo modules have no node_modules entry, so they are imported by path.
import {
    clearCatalog,
    clearCredentials,
    isAvailable,
    setCatalog,
    setCredentials,
    type WidgetCredentials,
} from '../../../modules/chart-widget'

import {
    buildCatalog,
    CATALOG_PIN_LIMIT,
    catalogJson,
    pinInsightShortId,
    type WidgetPinInsight,
} from './chartWidgetCatalog'

export type CredentialsSyncReason = 'sign_in' | 'refresh' | 'project_switch' | 'launch'

type ShortcutPage = PaginatedApi<FileSystemShortcutApi>

interface WidgetSession {
    scope: ProjectScope
    projectName: string
    generation: number
}

// Every write makes the OS reload each placed widget, so the sync remembers what it wrote and skips an identical write.
let writtenCredentials: string | null = null
let writtenCatalog: string | null = null
// `{host}|{project id}` of the catalog the widget holds, so a project without one gets its pin list prefetched.
let writtenCatalogProject: string | null = null
// False until the first clear of this launch, so a signed-out launch clears once whatever an earlier session left.
let cleared = false
// A catalog sync that started before a clear must not write the catalog of the session that ended.
let clearEpoch = 0
let catalogController: AbortController | null = null
// Keyed by `{host}|{project id}|{short_id}`: insights the server no longer returns, so a sync does not ask again.
const missingInsights = new Set<string>()
const prefetchedPinLists = new Set<string>()

function dataMode(): 'loading' | 'demo' | 'live' {
    if (!useDemoMode.persist.hasHydrated()) {
        return 'loading'
    }
    return useDemoMode.getState().enabled ? 'demo' : 'live'
}

function currentSession(): WidgetSession | null {
    const state = useAuthStore.getState()
    const owner = getSessionIdentity()
    if (state.status !== 'signed_in' || !state.host || !state.user || state.projectId === null) {
        return null
    }
    // A sign in stores the new tokens a moment before the store shows the new account. Until both agree, a write
    // would pair one account's token with another account's project.
    if (!getSessionTokens() || owner?.host !== state.host || owner.userUuid !== state.user.uuid) {
        return null
    }
    return {
        scope: { host: state.host.replace(/\/$/, ''), projectId: state.projectId },
        projectName: state.projectName ?? '',
        generation: sessionGeneration(),
    }
}

function isSameSession(session: WidgetSession, other: WidgetSession | null): boolean {
    return (
        other !== null &&
        other.generation === session.generation &&
        other.scope.host === session.scope.host &&
        other.scope.projectId === session.scope.projectId
    )
}

function currentCredentials(): WidgetCredentials | null {
    const session = currentSession()
    const tokens = getSessionTokens()
    const userUuid = useAuthStore.getState().user?.uuid
    if (!session || !tokens || !userUuid) {
        return null
    }
    return {
        host: session.scope.host,
        projectId: session.scope.projectId,
        projectName: session.projectName,
        accessToken: tokens.accessToken,
        expiresAt: tokens.expiresAt,
        userUuid,
    }
}

/** Removes the session copy, the catalog and every cached chart, so placed widgets ask to sign in. */
export function clearWidgetState(): void {
    writtenCredentials = null
    writtenCatalog = null
    writtenCatalogProject = null
    clearEpoch += 1
    catalogController?.abort()
    prefetchedPinLists.clear()
    missingInsights.clear()
    if (!isAvailable()) {
        return
    }
    // Each runs even when the other throws, because the token copy must go whatever happens to the catalog.
    // A failure leaves `cleared` false, so the next signed-out or demo sync tries again.
    let ok = true
    try {
        clearCredentials()
    } catch {
        ok = false
    }
    try {
        clearCatalog()
    } catch {
        ok = false
    }
    cleared = ok
}

export function syncWidgetCredentials(reason: CredentialsSyncReason): void {
    if (!isAvailable()) {
        return
    }
    const mode = dataMode()
    if (mode === 'loading') {
        return
    }
    if (mode === 'demo' || useAuthStore.getState().status === 'signed_out') {
        if (!cleared) {
            clearWidgetState()
        }
        return
    }
    const credentials = currentCredentials()
    if (!credentials) {
        return
    }
    const json = JSON.stringify(credentials)
    if (json === writtenCredentials) {
        return
    }
    try {
        setCredentials(credentials)
    } catch {
        // Nothing is recorded, so the next token or project change writes again.
        return
    }
    writtenCredentials = json
    cleared = false
    track('mobile_widget_credentials_synced', { reason })
}

function prefsKey(scope: ProjectScope): string {
    return `${scope.host}|${scope.projectId}`
}

function missingKey(scope: ProjectScope, shortId: string): string {
    return `${prefsKey(scope)}|${shortId}`
}

function insightOf(basic: InsightBasicApi): WidgetPinInsight | null {
    if (basic.deleted) {
        return null
    }
    return {
        insightId: basic.id,
        shortId: basic.short_id,
        name: basic.name || basic.derived_name || 'Untitled',
        query: basic.query,
    }
}

function cachedInsight(
    client: QueryClient,
    scope: ProjectScope,
    pin: PinView,
    shortId: string
): WidgetPinInsight | null | undefined {
    const basic = client.getQueryState<InsightBasicApi>(viewsKeys.pinMetadata(scope, shortId))
    const snapshot = client.getQueryState<InsightSnapshot>(
        viewsKeys.insight(scope, shortId, pin.kind === 'dashboard' ? pin.ref : null, overrideKey(null))
    )
    if (snapshot?.data && (!basic?.data || snapshot.data.readAt >= basic.dataUpdatedAt)) {
        return {
            insightId: snapshot.data.insightId,
            shortId: snapshot.data.shortId,
            name: snapshot.data.name,
            query: snapshot.data.query,
        }
    }
    if (basic?.data) {
        return insightOf(basic.data)
    }
    if (missingInsights.has(missingKey(scope, shortId))) {
        return null
    }
    return undefined
}

async function readInsight(
    client: QueryClient,
    scope: ProjectScope,
    shortId: string,
    isCurrent: () => boolean,
    signal: AbortSignal
): Promise<WidgetPinInsight | null> {
    // `projectPath()` reads the project when the request starts, so the session must still be the one the pins are from.
    const response = await listRead('insights', signal, () => {
        if (signal.aborted || !isCurrent()) {
            throw abortError()
        }
        return fetchInsightMetadata(shortId, signal)
    })
    if (signal.aborted || !isCurrent()) {
        throw abortError()
    }
    if (!response) {
        missingInsights.add(missingKey(scope, shortId))
        return null
    }
    // The shared cache entry, so the Views list's previews and later syncs read it without a request.
    client.setQueryData(viewsKeys.pinMetadata(scope, shortId), response)
    return insightOf(response)
}

async function pinMetadata(
    client: QueryClient,
    scope: ProjectScope,
    pins: readonly PinView[],
    isCurrent: () => boolean,
    signal: AbortSignal
): Promise<Map<string, WidgetPinInsight | null>> {
    const metadata = new Map<string, WidgetPinInsight | null>()
    const unread = new Set<string>()
    for (const pin of pins) {
        const shortId = pinInsightShortId(pin)
        if (!shortId || metadata.has(shortId)) {
            continue
        }
        const cached = cachedInsight(client, scope, pin, shortId)
        if (cached === undefined) {
            unread.add(shortId)
        } else {
            metadata.set(shortId, cached)
        }
    }
    // One at a time, so a first sync of many pins does not take a burst of the insights budget from the Views list.
    for (const shortId of unread) {
        try {
            metadata.set(shortId, await readInsight(client, scope, shortId, isCurrent, signal))
        } catch (error) {
            // A 429, a 503, an empty budget, no connection or a session change holds for every pin, so the rest
            // stay unread until the next sync. A 403 or 404 concerns this insight only.
            if (!(error instanceof ApiError) || error.status === 429 || error.status === 503) {
                break
            }
        }
    }
    return metadata
}

function viewsAccessible(): boolean {
    const access = featureAccessFor(
        {
            method: useAuthStore.getState().method,
            tokens: getSessionTokens(),
            reported: useScopeErrorStore.getState().reported.views,
        },
        'views'
    )
    return access.state === 'ok'
}

/**
 * Reads the pin list the way `usePins` does, same key and lane, so the catalog exists before the Views tab opens. Once
 * per project per session: after a failure the catalog waits for the next Views read.
 */
function prefetchPinList(client: QueryClient, session: WidgetSession): void {
    const key = `${session.generation}|${prefsKey(session.scope)}`
    if (prefetchedPinLists.has(key) || !viewsAccessible()) {
        return
    }
    prefetchedPinLists.add(key)
    void client.prefetchQuery({
        queryKey: viewsKeys.shortcuts(session.scope),
        // `projectPath()` reads the project when the request starts, so a read for an earlier session must not start.
        queryFn: ({ signal }) =>
            readShortcuts(signal, () => {
                if (!isSameSession(session, currentSession())) {
                    throw abortError()
                }
            }),
        staleTime: READ_FLOOR_MS,
        retry: retryListRead,
    })
}

async function writeCatalog(client: QueryClient, signal: AbortSignal): Promise<void> {
    if (!isAvailable() || dataMode() !== 'live') {
        return
    }
    const session = currentSession()
    if (!session) {
        return
    }
    const page = client.getQueryData<ShortcutPage>(viewsKeys.shortcuts(session.scope))
    if (!page && writtenCatalogProject !== prefsKey(session.scope)) {
        // A success lands in the query cache, whose subscription runs this sync again.
        prefetchPinList(client, session)
        return
    }
    // A list cut at the page size does not hold every pin, and the catalog replaces the widget's list whole.
    if (!page || !isCompleteShortcutPage(page)) {
        return
    }
    const prefs = usePinPrefs.getState().projects[prefsKey(session.scope)] ?? NO_PIN_PREFS
    let pins = pinsFromShortcuts(page.results, prefs).slice(0, CATALOG_PIN_LIMIT)
    const epoch = clearEpoch
    const isCurrent = (): boolean => epoch === clearEpoch && isSameSession(session, currentSession())
    const dashboards = pins.filter((pin) => pin.kind === 'dashboard' && !pinInsightShortId(pin))
    if (dashboards.length > 0) {
        try {
            const displays = await discoverPinDisplays(
                { client, scope: session.scope, demo: false },
                dashboards,
                signal,
                `widget-catalog:${prefsKey(session.scope)}`
            )
            pins = pins.map((pin) => {
                const display = displays[pin.shortcutId]
                return display ? { ...pin, display } : pin
            })
        } catch {
            // Keep the remaining pins available when a dashboard cannot be read.
        }
    }
    if (signal.aborted || !isCurrent()) {
        return
    }
    const metadata = await pinMetadata(client, session.scope, pins, isCurrent, signal)
    if (signal.aborted || !isCurrent()) {
        return
    }
    const body = buildCatalog(pins, metadata, { ...session.scope, projectName: session.projectName })
    const key = JSON.stringify(body)
    if (key === writtenCatalog) {
        return
    }
    setCatalog(catalogJson(body, Date.now()))
    writtenCatalog = key
    writtenCatalogProject = prefsKey(session.scope)
    cleared = false
    track('mobile_widget_catalog_synced', {
        pin_count: body.pins.length,
        eligible_count: body.pins.filter((pin) => pin.eligible).length,
    })
}

let catalogRun: Promise<void> | null = null
let catalogQueued = false

async function drainCatalog(client: QueryClient): Promise<void> {
    do {
        catalogQueued = false
        try {
            const controller = new AbortController()
            catalogController = controller
            await writeCatalog(client, controller.signal)
        } catch {
            // The widget keeps its last catalog; the next pin list read or display change tries again.
        }
    } while (catalogQueued)
}

export function syncWidgetCatalog(client: QueryClient): Promise<void> {
    catalogQueued = true
    if (!catalogRun) {
        // Auth subscribers run before selectProject resets queries. Start after that reset so it cannot cancel our prefetch.
        catalogRun = Promise.resolve()
            .then(() => drainCatalog(client))
            .finally(() => {
                catalogRun = null
                if (catalogQueued) {
                    void syncWidgetCatalog(client)
                }
            })
    }
    return catalogRun
}

function credentialsReason(state: AuthState, previous: AuthState): CredentialsSyncReason | null {
    if (state.status !== previous.status) {
        return previous.status === 'loading' ? 'launch' : 'sign_in'
    }
    if (state.status !== 'signed_in') {
        return null
    }
    if (state.host !== previous.host || state.user?.uuid !== previous.user?.uuid) {
        return 'sign_in'
    }
    if (state.projectId !== previous.projectId || state.projectName !== previous.projectName) {
        return 'project_switch'
    }
    return null
}

function isCurrentCatalogData(queryKey: QueryKey): boolean {
    const scope = currentSession()?.scope
    return Boolean(
        scope &&
            queryKey[0] === 'views' &&
            queryKey[1] === scope.host &&
            queryKey[2] === scope.projectId &&
            ['shortcuts', 'pin_metadata', 'insight', 'dashboard', 'smart_pin_displays'].includes(String(queryKey[3]))
    )
}

export function startChartWidgetSync(client: QueryClient): () => void {
    const syncCatalog = (): void => {
        void syncWidgetCatalog(client)
    }
    const stops = [
        addSessionEndTask(clearWidgetState),
        onSessionTokensChanged((change) => {
            syncWidgetCredentials(change === 'refresh' ? 'refresh' : 'sign_in')
            // The same account signing in again leaves the auth store's fields as they were, so only this sees it.
            if (change === 'session') {
                catalogController?.abort()
                syncCatalog()
            }
        }),
        useAuthStore.subscribe((state, previous) => {
            const reason = credentialsReason(state, previous)
            if (reason) {
                catalogController?.abort()
                syncWidgetCredentials(reason)
                syncCatalog()
            }
        }),
        useDemoMode.subscribe((state, previous) => {
            if (state.enabled !== previous.enabled) {
                syncWidgetCredentials('sign_in')
                syncCatalog()
            }
        }),
        useDemoMode.persist.onFinishHydration(() => {
            syncWidgetCredentials('launch')
            syncCatalog()
        }),
        usePinPrefs.subscribe((state, previous) => {
            if (state.projects !== previous.projects) {
                syncCatalog()
            }
        }),
        client.getQueryCache().subscribe((event) => {
            if (
                event.type === 'updated' &&
                event.action.type === 'success' &&
                isCurrentCatalogData(event.query.queryKey)
            ) {
                syncCatalog()
            }
        }),
    ]
    syncWidgetCredentials('launch')
    syncCatalog()
    return () => {
        catalogController?.abort()
        for (const stop of stops) {
            stop()
        }
    }
}
