import type { QueryClient, QueryKey } from '@tanstack/react-query'
import { AppState } from 'react-native'

import { backgroundReadDelay } from '@/api/budget'
import { ApiError } from '@/api/client'
import { fetchInsightMetadata, type InsightBasicApi, readInsight as readInsightResponse } from '@/api/insights'
import type { PaginatedApi, ProjectScope } from '@/api/reports'
import { serverNow } from '@/api/serverClock'
import { type FileSystemShortcutApi, isCompleteShortcutPage } from '@/api/shortcuts'
import { type AuthState, addSessionEndTask, useAuthStore } from '@/auth/authStore'
import { getSessionIdentity, getSessionTokens, onSessionTokensChanged, sessionGeneration } from '@/auth/tokens'
import { useDemoMode } from '@/demo/demoMode'
import { READ_FLOOR_MS } from '@/features/views/freshness'
import { listRead, readShortcuts, retryListRead } from '@/features/views/listReads'
import { NO_PIN_PREFS, usePinPrefs } from '@/features/views/pinPrefsStore'
import { discoverPinDisplays } from '@/features/views/useSmartPinDisplays'
import { featureAccessFor, useScopeErrorStore } from '@/features/views/useViewsAccess'
import { overrideKey, useItemErrors, viewsKeys } from '@/features/views/viewsCache'
import { abortError } from '@/lib/abort'
import { track } from '@/lib/analytics'
import { sleep } from '@/lib/sleep'
import { insightSnapshot } from '@/model/adapters/insightSnapshot'
import { pinsFromShortcuts } from '@/model/adapters/viewPins'
import type { InsightSnapshot, PinDisplay, PinView } from '@/model/views'

// Local Expo modules have no node_modules entry, so they are imported by path.
import {
    clearCatalog,
    clearCredentials,
    getWidgetState,
    isAvailable,
    setCatalog,
    setCredentials,
    type WidgetCredentials,
    type WidgetState,
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
// Account replacement runs cleanup before publishing its new tokens. Retired sessions must not start another sync.
let retiredGeneration: number | null = null
let catalogController: AbortController | null = null
let nextMetadataReadAt = 0
let widgetState: WidgetState | null = null
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
    const generation = sessionGeneration()
    if (generation === retiredGeneration) return null
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
        generation,
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
    widgetState = null
    nextMetadataReadAt = 0
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
    if (!widgetState?.installed || !viewsAccessible()) {
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
    const denied = Object.entries(useItemErrors.getState().errors).some(([key, error]) => {
        if (!['deleted', 'no_access', 'scope'].includes(error)) return false
        try {
            const queryKey: unknown[] = JSON.parse(key)
            return (
                queryKey[0] === 'views' &&
                queryKey[1] === scope.host &&
                queryKey[2] === scope.projectId &&
                ((queryKey[3] === 'insight' && queryKey[4] === shortId) ||
                    (queryKey[3] === 'dashboard' && pin.kind === 'dashboard' && queryKey[4] === pin.ref))
            )
        } catch {
            return false
        }
    })
    if (denied) return null
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
            snapshot: snapshot.data,
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
    pin: PinView,
    shortId: string,
    isCurrent: () => boolean,
    signal: AbortSignal,
    includeSnapshot: boolean
): Promise<WidgetPinInsight | null> {
    let startedAt = 0
    // `projectPath()` reads the project when the request starts, so the session must still be the one the pins are from.
    const response = await listRead('insights', signal, async () => {
        for (
            let delay = Math.max(nextMetadataReadAt - Date.now(), backgroundReadDelay('insights'));
            delay > 0;
            delay = Math.max(nextMetadataReadAt - Date.now(), backgroundReadDelay('insights'))
        ) {
            await sleep(delay, signal)
        }
        if (signal.aborted || !isCurrent()) {
            throw abortError()
        }
        startedAt = Date.now()
        nextMetadataReadAt = startedAt + 1000
        if (!includeSnapshot) return fetchInsightMetadata(shortId, signal)
        return readInsightResponse(
            { shortId, id: pin.display.insightId },
            {
                refresh: 'force_cache',
                signal,
                fromDashboard: pin.kind === 'dashboard' ? Number(pin.ref) : null,
            }
        )
    })
    if (signal.aborted || !isCurrent()) {
        throw abortError()
    }
    if (!response) {
        missingInsights.add(missingKey(scope, shortId))
        return null
    }
    // The shared cache entry, so the Views list's previews and later syncs read it without a request.
    const metadataKey = viewsKeys.pinMetadata(scope, shortId)
    if ((client.getQueryState(metadataKey)?.dataUpdatedAt ?? 0) <= startedAt) {
        client.setQueryData(metadataKey, response, { updatedAt: startedAt })
    }
    if (!('result' in response)) return insightOf(response)
    const snapshot = insightSnapshot(response, undefined, { readAt: startedAt, serverNow: serverNow() })
    const snapshotKey = viewsKeys.insight(scope, shortId, pin.kind === 'dashboard' ? pin.ref : null, overrideKey(null))
    if ((client.getQueryData<InsightSnapshot>(snapshotKey)?.readAt ?? 0) <= startedAt) {
        client.setQueryData(snapshotKey, snapshot)
    }
    const insight = insightOf(response)
    return insight ? { ...insight, snapshot } : null
}

async function loadPinMetadata(
    client: QueryClient,
    scope: ProjectScope,
    pins: readonly PinView[],
    isCurrent: () => boolean,
    signal: AbortSignal,
    selected: ReadonlySet<string>,
    publish: () => void
): Promise<void> {
    // Selected pins go first; a ready chart must not wait behind the rest of the picker.
    const prioritized = [
        ...pins.filter((pin) => selected.has(pin.shortcutId)),
        ...pins.filter((pin) => !selected.has(pin.shortcutId)),
    ]
    for (const pin of prioritized) {
        const shortId = pinInsightShortId(pin)
        if (!shortId || cachedInsight(client, scope, pin, shortId) !== undefined) continue
        try {
            await readInsight(client, scope, pin, shortId, isCurrent, signal, selected.has(pin.shortcutId))
            publish()
        } catch (error) {
            // A shared pause holds the remaining reads; an inaccessible insight concerns only its own pin.
            if (!(error instanceof ApiError) || error.status === 429 || error.status === 503) break
        }
    }
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

function readWidgetState(signal: AbortSignal): Promise<WidgetState> {
    return new Promise((resolve, reject) => {
        if (signal.aborted) {
            reject(abortError())
            return
        }
        const onAbort = (): void => reject(abortError())
        signal.addEventListener('abort', onAbort, { once: true })
        void getWidgetState()
            .then(resolve, reject)
            .finally(() => signal.removeEventListener('abort', onAbort))
    })
}

function cachedPins(client: QueryClient, session: WidgetSession): PinView[] | null {
    const page = client.getQueryData<ShortcutPage>(viewsKeys.shortcuts(session.scope))
    // A partial page cannot replace the complete picker.
    if (!page || !isCompleteShortcutPage(page)) return null
    const prefs = usePinPrefs.getState().projects[prefsKey(session.scope)] ?? NO_PIN_PREFS
    const automatic: Record<string, PinDisplay> = {}
    const previews = client.getQueryCache().findAll({
        queryKey: ['views', session.scope.host, session.scope.projectId, 'smart_pin_displays'],
    })
    for (const query of previews.sort((a, b) => a.state.dataUpdatedAt - b.state.dataUpdatedAt)) {
        Object.assign(automatic, query.state.data)
    }
    return pinsFromShortcuts(page.results, { ...prefs, display: { ...automatic, ...prefs.display } }).slice(
        0,
        CATALOG_PIN_LIMIT
    )
}

function selectedPins(
    client: QueryClient,
    session: WidgetSession,
    pins: readonly PinView[],
    presence: WidgetState
): Set<string> {
    const selected = new Set(presence.pinIds)
    if (presence.installed && presence.usesDefault) {
        const defaultPin =
            pins.find((pin) => {
                const shortId = pinInsightShortId(pin)
                return shortId && cachedInsight(client, session.scope, pin, shortId)
            }) ?? pins[0]
        if (defaultPin) selected.add(defaultPin.shortcutId)
    }
    return selected
}

function publishCachedCatalog(client: QueryClient): PinView[] | null {
    const session = currentSession()
    if (!isAvailable() || dataMode() !== 'live' || !session || !widgetState || !viewsAccessible()) return null
    const pins = cachedPins(client, session)
    if (!pins) return null
    const metadata = new Map<string, WidgetPinInsight | null>()
    for (const pin of pins) {
        const shortId = pinInsightShortId(pin)
        const cached = shortId ? cachedInsight(client, session.scope, pin, shortId) : undefined
        if (cached !== undefined) metadata.set(pin.shortcutId, cached)
    }
    const body = buildCatalog(
        pins,
        metadata,
        { ...session.scope, projectName: session.projectName },
        selectedPins(client, session, pins, widgetState)
    )
    const key = JSON.stringify(body)
    if (key !== writtenCatalog) {
        setCatalog(catalogJson(body, Date.now()))
        writtenCatalog = key
        writtenCatalogProject = prefsKey(session.scope)
        cleared = false
        track('mobile_widget_catalog_synced', {
            pin_count: body.pins.length,
            eligible_count: body.pins.filter((pin) => pin.eligible).length,
        })
    }
    return pins
}

async function writeCatalog(client: QueryClient, signal: AbortSignal): Promise<void> {
    if (!isAvailable() || dataMode() !== 'live') return
    const session = currentSession()
    if (!session) return
    if (!viewsAccessible()) {
        clearWidgetState()
        return
    }
    const presence = await readWidgetState(signal)
    if (signal.aborted || !isSameSession(session, currentSession())) return
    widgetState = presence
    if (!presence.installed) {
        writtenCredentials = null
        clearCredentials()
    } else {
        syncWidgetCredentials('launch')
    }
    let pins = publishCachedCatalog(client)
    if (!pins) {
        if (writtenCatalogProject !== prefsKey(session.scope)) prefetchPinList(client, session)
        return
    }
    const epoch = clearEpoch
    const isCurrent = (): boolean => !signal.aborted && epoch === clearEpoch && isSameSession(session, currentSession())
    const publish = (): void => {
        if (isCurrent()) publishCachedCatalog(client)
    }
    const selected = selectedPins(client, session, pins, presence)
    await loadPinMetadata(
        client,
        session.scope,
        pins.filter((pin) => selected.has(pin.shortcutId)),
        isCurrent,
        signal,
        selected,
        publish
    )
    // Resolve picker choices even before a widget selects them. Reuse Views previews, and keep manual choices intact.
    const prefs = usePinPrefs.getState().projects[prefsKey(session.scope)] ?? NO_PIN_PREFS
    const dashboards = pins.filter(
        (pin) => pin.kind === 'dashboard' && !pinInsightShortId(pin) && !prefs.display[pin.shortcutId]
    )
    dashboards.sort((a, b) => Number(selected.has(b.shortcutId)) - Number(selected.has(a.shortcutId)))
    for (const pin of dashboards) {
        if (!isCurrent()) return
        try {
            const displays = await discoverPinDisplays(
                { client, scope: session.scope, demo: false },
                [pin],
                signal,
                `widget-catalog:${prefsKey(session.scope)}`
            )
            if (!isCurrent()) return
            if (Object.keys(displays).length > 0) {
                client.setQueryData<Record<string, PinDisplay>>(
                    viewsKeys.smartPinDisplays(session.scope, 'widget-catalog'),
                    (previous) => ({ ...previous, ...displays })
                )
                publish()
            }
        } catch {
            // Keep the remaining picker choices available when one dashboard cannot be read.
        }
    }
    if (!isCurrent()) return
    pins = cachedPins(client, session) ?? []
    await loadPinMetadata(
        client,
        session.scope,
        pins,
        isCurrent,
        signal,
        selectedPins(client, session, pins, presence),
        publish
    )
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
    // Cache successes publish even while an unrelated metadata request is waiting.
    try {
        publishCachedCatalog(client)
    } catch {
        /* The next sync retries a failed native write. */
    }
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
    const foreground = AppState.addEventListener('change', (state) => {
        if (state === 'active') {
            catalogController?.abort()
            syncCatalog()
        }
    })
    const stops = [
        addSessionEndTask(() => {
            retiredGeneration = sessionGeneration()
            clearWidgetState()
        }),
        () => foreground.remove(),
        useScopeErrorStore.subscribe(() => {
            catalogController?.abort()
            syncCatalog()
        }),
        useItemErrors.subscribe(syncCatalog),
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
                catalogController?.abort()
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
