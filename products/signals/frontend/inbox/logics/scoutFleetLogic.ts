import { MakeLogicType, actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api-error'
import { dayjs } from 'lib/dayjs'
import { reconcileById } from 'lib/utils/objects'
import { aiConsentLogic } from 'scenes/settings/organization/aiConsentLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    signalsScoutChatTasksCreate,
    signalsScoutConfigDestroy,
    signalsScoutConfigList,
    signalsScoutConfigRun,
    signalsScoutConfigUpdate,
    signalsScoutMetadataGet,
    signalsScoutRunsFindingsSummary,
    signalsScoutRunsList,
    signalsScoutRunsRecentPerScout,
} from 'products/signals/frontend/generated/api'
import type {
    FleetFindingsSummaryApi,
    PatchedSignalScoutConfigUpdateApi,
    ScoutMetadataApi,
    SignalScoutConfigApi,
} from 'products/signals/frontend/generated/api.schemas'
import { llmSkillsNameArchiveCreate } from 'products/skills/frontend/generated/api'

import {
    captureScoutAction,
    captureScoutChatStarted,
    captureScoutConfigChanged,
    ScoutChatType,
    ScoutSurface,
} from '../inboxAnalytics'
import { SignalScoutRunSummary } from '../types'
import { aiConsentDisabledReason } from '../utils/aiConsent'
import { compareScoutsByName, scoutGroup, ScoutRosterRow } from '../utils/scoutGroups'

export type ScoutEnabledFilter = 'all' | 'enabled' | 'disabled'
import {
    computeFleetSummary,
    computeScoutRollups,
    FleetSummary,
    isSettledRun,
    prettifyScoutSkillName,
    SCOUT_ROSTER_WINDOW_HOURS,
    SCOUT_RUNS_PER_SCOUT,
    SCOUT_RUNS_WINDOW_HOURS,
    ScoutRollup,
} from '../utils/scoutRunsWindow'
import { configMatchesScoutTags, listScoutTagOptions } from '../utils/scoutTags'
import type { ScoutTagOption } from '../utils/scoutTags'

// Exported because kea-typegen writes an import for it into any logic that connects `scoutConfigs`,
// which Replay Vision's scanner scouts do.
export type SignalScoutConfig = SignalScoutConfigApi
type SignalScoutConfigUpdate = PatchedSignalScoutConfigUpdateApi

/**
 * One `Scout config changed` per field the request carried. A schedule switch patches both
 * `run_interval_minutes` and `run_cron_schedule` at once, and collapsing those into a single event
 * would make the `setting` breakdown misreport which control the user actually moved.
 */
function captureScoutConfigUpdates(
    config: SignalScoutConfig | undefined,
    updates: SignalScoutConfigUpdate,
    success: boolean
): void {
    for (const [setting, newValue] of Object.entries(updates)) {
        captureScoutConfigChanged({
            skillName: config?.skill_name ?? '',
            scoutOrigin: config?.scout_origin ?? null,
            setting,
            oldValue: config ? (config as unknown as Record<string, unknown>)[setting] : null,
            newValue,
            success,
        })
    }
}

// Fleet runs are refetched on a slow cadence so "running now" / recent emissions
// stay live without hammering the capped runs endpoint (desktop: 60s).
const RUNS_REFETCH_INTERVAL_MS = 60_000
// The findings feed's fixed lookback: the runs endpoint caps each page at 100 rows newest-first, so
// covering the whole window means walking back page-by-page via a `date_to` cursor (the oldest run's
// `started_at`, as the backend documents). MAX_RUNS_PAGES bounds the walk so a pathologically busy
// fleet can't spin forever — hitting it flags the window truncated. Per-scout stats don't pay this:
// `loadScoutRuns` gets each scout's last N runs from one ranked query.
const RUNS_PAGE_LIMIT = 100
const MAX_RUNS_PAGES = 15

// Roster filter state also lives in the URL so a filtered view survives a refresh and is shareable.
// The search param is written on this debounce, so typing does not rewrite the URL per keystroke.
const ROSTER_SEARCH_DEBOUNCE_MS = 600

interface RosterFilterState {
    scoutSearch: string
    scoutEnabledFilter: ScoutEnabledFilter
    selectedScoutTags: string[]
}

// Merge the roster filters into `base`, writing only params that differ from the default so the bare
// `/inbox/scouts` URL stays clean.
function rosterFilterSearchParams(base: Record<string, any>, filters: RosterFilterState): Record<string, any> {
    const params = { ...base }
    const search = filters.scoutSearch.trim()
    if (search) {
        params.scoutSearch = search
    } else {
        delete params.scoutSearch
    }
    if (filters.scoutEnabledFilter !== 'all') {
        params.scoutEnabled = filters.scoutEnabledFilter
    } else {
        delete params.scoutEnabled
    }
    if (filters.selectedScoutTags.length > 0) {
        params.scoutTags = filters.selectedScoutTags.join(',')
    } else {
        delete params.scoutTags
    }
    return params
}

// kea-router parses `?scoutSearch=123` into a number and `?scoutSearch=true` into a boolean, so a
// string-only check would drop searches and tags that a person can type. Read a scalar back as the
// text it came from, and reject the array and object forms, which no roster param ever takes.
function readTextParam(value: unknown): string {
    if (typeof value === 'string') {
        return value
    }
    if (typeof value === 'number' || typeof value === 'boolean') {
        return String(value)
    }
    return ''
}

function parseRosterFilterSearchParams(searchParams: Record<string, any>): RosterFilterState {
    const tags = readTextParam(searchParams.scoutTags)
    return {
        scoutSearch: readTextParam(searchParams.scoutSearch),
        scoutEnabledFilter:
            searchParams.scoutEnabled === 'enabled' || searchParams.scoutEnabled === 'disabled'
                ? searchParams.scoutEnabled
                : 'all',
        selectedScoutTags: tags ? tags.split(',').filter(Boolean) : [],
    }
}

// The URL mirrors what the tag control shows, and that control only lists tags the fleet still uses.
// Until the configs load there is nothing to check a selection against, so the raw selection stands
// and a shared link keeps its tags.
function rosterFilterUrlState(values: scoutFleetLogicValues): RosterFilterState {
    return {
        scoutSearch: values.scoutSearch,
        scoutEnabledFilter: values.scoutEnabledFilter,
        selectedScoutTags: values.scoutConfigs === null ? values.selectedScoutTags : values.activeScoutTags,
    }
}

function sameTags(a: string[], b: string[]): boolean {
    return a.length === b.length && a.every((tag, index) => tag === b[index])
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutFleetLogicValues {
    dataProcessingAccepted: boolean // aiConsentLogic
    dataProcessingApprovalDisabledReason: string | null // aiConsentLogic
    activeScoutTags: string[]
    aiConsentDisabledReason: string | null
    customScoutCount: number
    deletingScoutIds: string[]
    emittedFindingsSummary: {
        authoredReportCount: number
        count: number
        editedReportCount: number
        latestAt: string | null
        runCount: number
        scoutCount: number
    }
    enabledCount: number
    fleetFindingsSummary: FleetFindingsSummaryApi | null
    fleetFindingsSummaryLoadedOnce: boolean
    fleetFindingsSummaryLoading: boolean
    fleetSummary: FleetSummary | null
    lastRunAt: string | null
    manualRunScoutIds: string[]
    rollups: Map<string, ScoutRollup>
    rosterEvaluatedAt: number
    rosterScouts: ScoutRosterRow[]
    runningChatType: ScoutChatType | null
    runsWindow: {
        complete: boolean
        runs: SignalScoutRunSummary[]
    }
    runsWindowLoadedOnce: boolean
    runsWindowLoading: boolean
    scoutBannerMessage: string | null
    scoutConfigs: SignalScoutConfig[] | null
    scoutConfigsLoading: boolean
    scoutEnabledFilter: ScoutEnabledFilter
    scoutMetadata: ScoutMetadataApi | null
    scoutMetadataLoading: boolean
    scoutRuns: SignalScoutRunSummary[]
    scoutRunsLoadedOnce: boolean
    scoutRunsLoading: boolean
    scoutSearch: string
    scoutTagOptions: ScoutTagOption[]
    selectedScoutTags: string[]
    updatingScoutIds: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutFleetLogicActions {
    deleteScout: (
        configId: string,
        surface?: ScoutSurface
    ) => {
        configId: string
        surface: ScoutSurface
    }
    deleteScoutFinished: (configId: string) => {
        configId: string
    }
    hydrateRosterFilters: (
        search: string,
        filter: ScoutEnabledFilter,
        tags: string[]
    ) => {
        filter: ScoutEnabledFilter
        search: string
        tags: string[]
    }
    loadFleetFindingsSummary: () => any
    loadFleetFindingsSummaryFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadFleetFindingsSummarySuccess: (
        fleetFindingsSummary: FleetFindingsSummaryApi | null,
        payload?: any
    ) => {
        fleetFindingsSummary: FleetFindingsSummaryApi | null
        payload?: any
    }
    loadRunsWindow: () => any
    loadRunsWindowFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRunsWindowSuccess: (
        runsWindow: {
            complete: boolean
            runs: SignalScoutRunSummary[]
        },
        payload?: any
    ) => {
        runsWindow: {
            complete: boolean
            runs: SignalScoutRunSummary[]
        }
        payload?: any
    }
    loadScoutConfigs: () => any
    loadScoutConfigsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadScoutConfigsSuccess: (
        scoutConfigs: SignalScoutConfigApi[] | null,
        payload?: any
    ) => {
        scoutConfigs: SignalScoutConfigApi[] | null
        payload?: any
    }
    loadScoutMetadata: () => any
    loadScoutMetadataFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadScoutMetadataSuccess: (
        scoutMetadata: ScoutMetadataApi | null,
        payload?: any
    ) => {
        scoutMetadata: ScoutMetadataApi | null
        payload?: any
    }
    loadScoutRuns: () => any
    loadScoutRunsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadScoutRunsSuccess: (
        scoutRuns: SignalScoutRunSummary[],
        payload?: any
    ) => {
        scoutRuns: SignalScoutRunSummary[]
        payload?: any
    }
    patchScoutConfigLocally: (
        configId: string,
        updates: Partial<SignalScoutConfig> | SignalScoutConfigUpdate
    ) => {
        configId: string
        updates: Partial<SignalScoutConfigApi> | PatchedSignalScoutConfigUpdateApi
    }
    removeScoutConfigLocally: (configId: string) => {
        configId: string
    }
    runScoutNow: (configId: string) => {
        configId: string
    }
    runScoutNowFinished: (configId: string) => {
        configId: string
    }
    setRosterEvaluatedAt: (evaluatedAt: number) => {
        evaluatedAt: number
    }
    setScoutEnabledFilter: (filter: ScoutEnabledFilter) => {
        filter: ScoutEnabledFilter
    }
    setScoutSearch: (search: string) => {
        search: string
    }
    setScoutTagFilter: (tags: string[]) => {
        tags: string[]
    }
    startRunsPolling: () => {
        value: true
    }
    startScoutChatTask: (
        chatType: ScoutChatType,
        taskLabel: string
    ) => {
        chatType: ScoutChatType
        taskLabel: string
    }
    startScoutChatTaskFailure: () => {
        value: true
    }
    startScoutChatTaskSuccess: () => {
        value: true
    }
    stopRunsPolling: () => {
        value: true
    }
    updateScoutConfig: (
        configId: string,
        updates: SignalScoutConfigUpdate
    ) => {
        configId: string
        updates: PatchedSignalScoutConfigUpdateApi
    }
    updateScoutConfigFinished: (configId: string) => {
        configId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface scoutFleetLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        aiConsentDisabledReason: (
            dataProcessingAccepted: boolean,
            dataProcessingApprovalDisabledReason: string | null
        ) => string | null
        rollups: (scoutRuns: SignalScoutRunSummary[]) => Map<string, ScoutRollup>
        fleetSummary: (
            scoutConfigs: SignalScoutConfigApi[] | null,
            rollups: Map<string, ScoutRollup>
        ) => FleetSummary | null
        scoutBannerMessage: (scoutMetadata: ScoutMetadataApi | null) => string | null
        enabledCount: (scoutConfigs: SignalScoutConfigApi[] | null) => number
        lastRunAt: (scoutConfigs: SignalScoutConfigApi[] | null) => string | null
        scoutTagOptions: (scoutConfigs: SignalScoutConfigApi[] | null) => ScoutTagOption[]
        activeScoutTags: (selectedScoutTags: string[], scoutTagOptions: ScoutTagOption[]) => string[]
        rosterScouts: (
            scoutConfigs: SignalScoutConfigApi[] | null,
            rollups: Map<string, ScoutRollup>,
            rosterEvaluatedAt: number,
            activeScoutTags: string[],
            scoutSearch: string,
            scoutEnabledFilter: ScoutEnabledFilter
        ) => ScoutRosterRow[]
        emittedFindingsSummary: (fleetFindingsSummary: FleetFindingsSummaryApi | null) => {
            authoredReportCount: number
            count: number
            editedReportCount: number
            latestAt: string | null
            runCount: number
            scoutCount: number
        }
        customScoutCount: (scoutConfigs: SignalScoutConfigApi[] | null) => number
    }
}

export type scoutFleetLogicType = MakeLogicType<
    scoutFleetLogicValues,
    scoutFleetLogicActions,
    Record<string, any>,
    scoutFleetLogicMeta
>

/**
 * Cloud port of desktop's scouts fleet hooks (`useScoutConfigs`, `useScoutRuns`,
 * `useScoutConfigMutations`, `useScoutChatTask`). Owns:
 * - loaders for scout configs + the recent runs window
 * - optimistic config mutations (enable/disable, live/dry-run, cadence)
 * - the runs-window rollups + fleet summary selectors
 * - "Make a scout" / fleet-overview / recent-signals chat task-kickoffs
 */
export const scoutFleetLogic = kea<scoutFleetLogicType>([
    path(['scenes', 'inbox', 'logics', 'scoutFleetLogic']),

    connect({
        values: [aiConsentLogic, ['dataProcessingAccepted', 'dataProcessingApprovalDisabledReason']],
    }),

    actions({
        updateScoutConfig: (configId: string, updates: SignalScoutConfigUpdate) => ({ configId, updates }),
        updateScoutConfigFinished: (configId: string) => ({ configId }),
        // A full server config doubles as a local patch when reconciling optimistic edits.
        patchScoutConfigLocally: (configId: string, updates: SignalScoutConfigUpdate | Partial<SignalScoutConfig>) => ({
            configId,
            updates,
        }),
        deleteScout: (configId: string, surface: ScoutSurface = 'fleet_list') => ({ configId, surface }),
        deleteScoutFinished: (configId: string) => ({ configId }),
        removeScoutConfigLocally: (configId: string) => ({ configId }),
        setScoutTagFilter: (tags: string[]) => ({ tags }),
        setScoutSearch: (search: string) => ({ search }),
        setRosterEvaluatedAt: (evaluatedAt: number) => ({ evaluatedAt }),
        setScoutEnabledFilter: (filter: ScoutEnabledFilter) => ({ filter }),
        // Bulk-applies the roster filters from the URL. Kept out of `actionToUrl` so hydrating from a
        // link does not echo the same URL back as a fresh history entry.
        hydrateRosterFilters: (search: string, filter: ScoutEnabledFilter, tags: string[]) => ({
            search,
            filter,
            tags,
        }),
        runScoutNow: (configId: string) => ({ configId }),
        runScoutNowFinished: (configId: string) => ({ configId }),
        // Started/stopped by the fleet-list component so the always-mounted setup widget
        // (which only reads configs) doesn't trigger the paginated runs-window polling.
        startRunsPolling: true,
        stopRunsPolling: true,
        startScoutChatTask: (chatType: ScoutChatType, taskLabel: string) => ({
            chatType,
            taskLabel,
        }),
        startScoutChatTaskSuccess: true,
        startScoutChatTaskFailure: true,
    }),

    loaders(({ values }) => ({
        scoutConfigs: [
            null as SignalScoutConfig[] | null,
            {
                loadScoutConfigs: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    try {
                        const configs = await signalsScoutConfigList(String(teamId))
                        // The 60s poll refetches all configs every cycle. Reconcile against the previous
                        // list so an unchanged fleet keeps the same references — otherwise the whole
                        // roster re-renders on every poll even when nothing changed.
                        return reconcileById(values.scoutConfigs ?? [], configs, (config) => config.id)
                    } catch (error) {
                        // A stale project id left in the URL by a project switch, or a member without
                        // access, are expected — degrade to the same null the no-team guard returns
                        // instead of reporting them. Anything else, notably a 5xx, still throws so a
                        // real backend failure keeps reaching error tracking.
                        if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
        // Cheap fleet-wide output tally for the "Scout findings" callout — one backend query over
        // runs that produced output (findings or report-channel activity), so the callout no longer
        // waits on the full paginated runs-window walk (which could take ~10s and was the reason the
        // callout appeared long after the modal opened).
        // Feeds the announcement banner: an operator-set notice on the `signals-scout` flag payload
        // (rollout, run-limit changes) that has to reach the roster without a frontend deploy.
        scoutMetadata: [
            null as ScoutMetadataApi | null,
            {
                loadScoutMetadata: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    try {
                        return await signalsScoutMetadataGet(String(teamId))
                    } catch {
                        // Only the optional banner reads this, so a blip degrades to no banner.
                        return null
                    }
                },
            },
        ],
        fleetFindingsSummary: [
            null as FleetFindingsSummaryApi | null,
            {
                loadFleetFindingsSummary: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await signalsScoutRunsFindingsSummary(String(teamId), {
                        window_hours: SCOUT_ROSTER_WINDOW_HOURS,
                    })
                },
            },
        ],
        // Each scout's most recent runs — what every per-scout stat (rollups, run history, fleet
        // success/emit rate) is computed over. One ranked query, so no page walk and no truncation:
        // the response is bounded by the fleet size, not by how often the fleet runs.
        scoutRuns: [
            [] as SignalScoutRunSummary[],
            {
                loadScoutRuns: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.scoutRuns
                    }
                    const runs = await signalsScoutRunsRecentPerScout(String(teamId), {
                        per_scout_limit: SCOUT_RUNS_PER_SCOUT,
                    })
                    // Reuse prior references for unchanged runs so the 60s poll doesn't churn every
                    // run's identity and needlessly re-render the memoized run/emission rows. Live
                    // (running/queued) runs are never reused: their rows show a wall-clock duration
                    // that must keep advancing with each poll.
                    return reconcileById(values.scoutRuns, runs, (run) => run.run_id, isSettledRun)
                },
            },
        ],
        runsWindow: [
            { runs: [] as SignalScoutRunSummary[], complete: true } as {
                runs: SignalScoutRunSummary[]
                complete: boolean
            },
            {
                loadRunsWindow: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return values.runsWindow
                    }
                    // Walk the full window newest→oldest, paginating via a `date_to` cursor so
                    // every scout shows its real run history (not just the fleet-wide newest 100).
                    const windowStart = dayjs().subtract(SCOUT_RUNS_WINDOW_HOURS, 'hours').toISOString()
                    const seen = new Set<string>()
                    const runs: SignalScoutRunSummary[] = []
                    let cursor: string | undefined
                    let complete = false

                    for (let page = 0; page < MAX_RUNS_PAGES; page++) {
                        const pageRuns = await signalsScoutRunsList(String(teamId), {
                            limit: RUNS_PAGE_LIMIT,
                            date_from: windowStart,
                            date_to: cursor,
                        })
                        for (const run of pageRuns) {
                            // `date_to` is exclusive, so a boundary row can reappear on the next
                            // page — dedupe by run_id to be safe.
                            if (!seen.has(run.run_id)) {
                                seen.add(run.run_id)
                                runs.push(run)
                            }
                        }
                        // A short page means we reached the start of the window — nothing older left.
                        if (pageRuns.length < RUNS_PAGE_LIMIT) {
                            complete = true
                            break
                        }
                        // Cursor on `created_at` — the exact field the endpoint filters/orders on, so
                        // the walk can't skip runs (`started_at` is the TaskRun's time and can differ).
                        const oldest = pageRuns[pageRuns.length - 1]
                        // No usable cursor, or the cursor can't advance (a full page of identical
                        // timestamps): stop, but the page was full so the window is NOT complete.
                        if (!oldest.created_at || oldest.created_at === cursor) {
                            break
                        }
                        cursor = oldest.created_at
                    }

                    // Reuse prior references for unchanged runs so the 60s poll doesn't churn every
                    // run's identity and needlessly re-render the memoized run/emission rows. Live
                    // (running/queued) runs are never reused: their rows show a wall-clock duration
                    // that must keep advancing with each poll.
                    return {
                        runs: reconcileById(values.runsWindow.runs, runs, (run) => run.run_id, isSettledRun),
                        complete,
                    }
                },
            },
        ],
    })),

    reducers({
        // Tracks which CTA's chat-task kickoff is mid-flight, keyed by its chat type, so only the
        // pressed chip spins (the others merely disable). A shared boolean spun all three at once.
        runningChatType: [
            null as ScoutChatType | null,
            {
                startScoutChatTask: (_, { chatType }) => chatType,
                startScoutChatTaskSuccess: () => null,
                startScoutChatTaskFailure: () => null,
            },
        ],
        selectedScoutTags: [
            [] as string[],
            {
                setScoutTagFilter: (_, { tags }) => tags,
                hydrateRosterFilters: (_, { tags }) => tags,
            },
        ],
        scoutSearch: [
            '',
            {
                setScoutSearch: (_, { search }) => search,
                hydrateRosterFilters: (_, { search }) => search,
            },
        ],
        scoutEnabledFilter: [
            'all' as ScoutEnabledFilter,
            {
                setScoutEnabledFilter: (_, { filter }) => filter,
                hydrateRosterFilters: (_, { filter }) => filter,
            },
        ],
        rosterEvaluatedAt: [
            0,
            {
                setRosterEvaluatedAt: (_, { evaluatedAt }) => evaluatedAt,
            },
        ],
        scoutConfigs: [
            null as SignalScoutConfig[] | null,
            {
                // Optimistic patch; the listener reconciles against the server response.
                patchScoutConfigLocally: (state, { configId, updates }) =>
                    state?.map((config) => (config.id === configId ? { ...config, ...updates } : config)) ?? state,
                // Drop a deleted row from the list once the backend confirms removal.
                removeScoutConfigLocally: (state, { configId }) =>
                    state?.filter((config) => config.id !== configId) ?? state,
            },
        ],
        // Scouts with a delete request in flight — drives the delete button's loading/disabled state
        // so a slow request can't be submitted twice from the still-visible row.
        deletingScoutIds: [
            [] as string[],
            {
                deleteScout: (state, { configId }) => (state.includes(configId) ? state : [...state, configId]),
                deleteScoutFinished: (state, { configId }) => state.filter((id) => id !== configId),
            },
        ],
        updatingScoutIds: [
            [] as string[],
            {
                updateScoutConfig: (state, { configId }) => (state.includes(configId) ? state : [...state, configId]),
                updateScoutConfigFinished: (state, { configId }) => state.filter((id) => id !== configId),
            },
        ],
        manualRunScoutIds: [
            [] as string[],
            {
                runScoutNow: (state, { configId }) => (state.includes(configId) ? state : [...state, configId]),
                runScoutNowFinished: (state, { configId }) => state.filter((id) => id !== configId),
            },
        ],
        // Flips true the first time the runs window loads *successfully* and stays true across the
        // 60s polls. Consumers (e.g. the scout detail Signals section) use it to tell "not loaded
        // yet" from "loaded, genuinely empty" without flickering a skeleton on polls. Deliberately
        // NOT set on failure: a failed first load must keep showing loading (the poll retries),
        // not latch and let a consumer render a false "no signals" empty state over no data.
        runsWindowLoadedOnce: [
            false,
            {
                loadRunsWindowSuccess: () => true,
            },
        ],
        // Same "loaded once, never on failure" contract as `runsWindowLoadedOnce`, for the per-scout
        // surfaces: it's what lets the scout detail sections tell "not loaded yet" from "loaded,
        // genuinely empty" without flashing a skeleton on every poll.
        scoutRunsLoadedOnce: [
            false,
            {
                loadScoutRunsSuccess: () => true,
            },
        ],
        // Flips true once the cheap findings summary lands, so the callout can tell "not loaded yet"
        // from "loaded, genuinely zero" without the full runs window. Like `runsWindowLoadedOnce`,
        // deliberately NOT set on failure: a failed load keeps the callout hidden, not falsely empty.
        fleetFindingsSummaryLoadedOnce: [
            false,
            {
                loadFleetFindingsSummarySuccess: () => true,
            },
        ],
    }),

    selectors({
        aiConsentDisabledReason: [
            (s) => [s.dataProcessingAccepted, s.dataProcessingApprovalDisabledReason],
            (dataProcessingAccepted: boolean, dataProcessingApprovalDisabledReason: string | null): string | null =>
                aiConsentDisabledReason(dataProcessingAccepted, dataProcessingApprovalDisabledReason),
        ],
        rollups: [
            (s) => [s.scoutRuns],
            (scoutRuns: SignalScoutRunSummary[]): Map<string, ScoutRollup> => computeScoutRollups(scoutRuns),
        ],
        fleetSummary: [
            (s) => [s.scoutConfigs, s.rollups],
            (scoutConfigs: SignalScoutConfig[] | null, rollups: Map<string, ScoutRollup>): FleetSummary | null =>
                scoutConfigs ? computeFleetSummary(scoutConfigs, rollups) : null,
        ],
        scoutBannerMessage: [
            (s) => [s.scoutMetadata],
            (scoutMetadata: ScoutMetadataApi | null): string | null => scoutMetadata?.banner_message ?? null,
        ],
        enabledCount: [
            (s) => [s.scoutConfigs],
            (scoutConfigs: SignalScoutConfig[] | null): number =>
                scoutConfigs?.filter((config) => config.enabled).length ?? 0,
        ],
        lastRunAt: [
            (s) => [s.scoutConfigs],
            (scoutConfigs: SignalScoutConfig[] | null): string | null => {
                let latest: string | null = null
                for (const config of scoutConfigs ?? []) {
                    if (config.last_run_at && (!latest || config.last_run_at > latest)) {
                        latest = config.last_run_at
                    }
                }
                return latest
            },
        ],
        scoutTagOptions: [
            (s) => [s.scoutConfigs],
            (scoutConfigs: SignalScoutConfig[] | null): ScoutTagOption[] => listScoutTagOptions(scoutConfigs ?? []),
        ],
        activeScoutTags: [
            (s) => [s.selectedScoutTags, s.scoutTagOptions],
            (selectedScoutTags: string[], scoutTagOptions: ScoutTagOption[]): string[] =>
                selectedScoutTags.filter((tag) => scoutTagOptions.some((option) => option.tag === tag)),
        ],
        /**
         * The roster as one alphabetical list, each row tagged with its lifecycle group and narrowed
         * by the roster's own chrome (search and the tag filter). `rosterEvaluatedAt` advances only
         * when time changes a lifecycle group, so settled polls keep this selector's output stable.
         */
        rosterScouts: [
            (s) => [
                s.scoutConfigs,
                s.rollups,
                s.rosterEvaluatedAt,
                s.activeScoutTags,
                s.scoutSearch,
                s.scoutEnabledFilter,
            ],
            (
                scoutConfigs: SignalScoutConfig[] | null,
                rollups: Map<string, ScoutRollup>,
                rosterEvaluatedAt: number,
                activeScoutTags: string[],
                scoutSearch: string,
                scoutEnabledFilter: ScoutEnabledFilter
            ): ScoutRosterRow[] => {
                const query = scoutSearch.trim().toLowerCase()
                const now = new Date(rosterEvaluatedAt)
                return [...(scoutConfigs ?? [])]
                    .filter((config) => configMatchesScoutTags(config, activeScoutTags))
                    .filter(
                        (config) =>
                            scoutEnabledFilter === 'all' || config.enabled === (scoutEnabledFilter === 'enabled')
                    )
                    .filter(
                        (config) =>
                            !query ||
                            prettifyScoutSkillName(config.skill_name).toLowerCase().includes(query) ||
                            config.skill_name.toLowerCase().includes(query) ||
                            (config.description ?? '').toLowerCase().includes(query)
                    )
                    .sort(compareScoutsByName)
                    .map((config) => ({ config, group: scoutGroup(config, rollups.get(config.skill_name), now) }))
            },
        ],
        // Fleet-wide output tally for the "Scout findings" callout, read from the cheap backend
        // summary rather than the paginated runs window. Covers both emit channels — legacy findings
        // and reports authored/edited via the report channel — over the same capped set the findings
        // page renders (most recent 120 output runs in the window), so the callout can't
        // over-advertise. Zeroed until the summary loads.
        emittedFindingsSummary: [
            (s) => [s.fleetFindingsSummary],
            (
                fleetFindingsSummary: FleetFindingsSummaryApi | null
            ): {
                count: number
                scoutCount: number
                authoredReportCount: number
                editedReportCount: number
                runCount: number
                latestAt: string | null
            } => ({
                count: fleetFindingsSummary?.count ?? 0,
                scoutCount: fleetFindingsSummary?.scout_count ?? 0,
                authoredReportCount: fleetFindingsSummary?.authored_report_count ?? 0,
                editedReportCount: fleetFindingsSummary?.edited_report_count ?? 0,
                runCount: fleetFindingsSummary?.run_count ?? 0,
                latestAt: fleetFindingsSummary?.latest_at ?? null,
            }),
        ],
        customScoutCount: [
            (s) => [s.scoutConfigs],
            (scoutConfigs: SignalScoutConfig[] | null): number =>
                scoutConfigs?.filter((config) => config.scout_origin === 'custom').length ?? 0,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        loadScoutRunsSuccess: () => {
            const evaluatedAt = new Date(values.rosterEvaluatedAt)
            const now = new Date()
            const groupChanged = (values.scoutConfigs ?? []).some((config) => {
                const rollup = values.rollups.get(config.skill_name)
                return scoutGroup(config, rollup, evaluatedAt) !== scoutGroup(config, rollup, now)
            })
            if (groupChanged) {
                actions.setRosterEvaluatedAt(now.valueOf())
            }
        },
        setScoutTagFilter: ({ tags }) => {
            captureScoutAction({
                actionType: 'filter_tags',
                surface: 'fleet_list',
                extra: {
                    tags,
                    filter_match_count: tags.length
                        ? (values.scoutConfigs ?? []).filter((config) => configMatchesScoutTags(config, tags)).length
                        : undefined,
                },
            })
        },
        setScoutEnabledFilter: ({ filter }) => {
            captureScoutAction({
                actionType: 'filter_enabled',
                surface: 'fleet_list',
                // `filter_match_count`: rows still shown after every filter.
                extra: { filter, filter_match_count: values.rosterScouts.length },
            })
        },
        // Debounced so a burst of keystrokes settles once, on pause. The URL is rewritten through
        // `replace`, so Back does not step through every partial query. Analytics ride the same pause:
        // a typed query reports once, clearing reports nothing. The event payload carries only the
        // length, not the term. That is no longer a privacy boundary: the term is in the URL, so
        // `$current_url` carries it on this event and on every later one from the same page.
        setScoutSearch: async ({ search }, breakpoint) => {
            const searchedPathname = router.values.location.pathname
            await breakpoint(ROSTER_SEARCH_DEBOUNCE_MS)
            // Hydrating from the URL replaces the search without aborting this breakpoint, so the
            // typed query can be stale by now. Drop it: the hydrated search owns the URL, and
            // reporting the abandoned query here would pair its length with the new match count.
            if (values.scoutSearch !== search) {
                return
            }
            // The logic stays mounted across a master-detail navigation, so the breakpoint does not
            // abort on a same-scene route change. Only write the roster filter if the user is still on
            // the route they searched from — otherwise the delayed write lands a roster param on a
            // route it does not own (e.g. an open scout's detail URL).
            if (router.values.location.pathname === searchedPathname) {
                router.actions.replace(
                    router.values.location.pathname,
                    rosterFilterSearchParams(router.values.searchParams, rosterFilterUrlState(values)),
                    router.values.hashParams
                )
            }
            const query = search.trim()
            if (!query) {
                return
            }
            captureScoutAction({
                actionType: 'search_scouts',
                surface: 'fleet_list',
                extra: { search_length: query.length, filter_match_count: values.rosterScouts.length },
            })
        },
        runScoutNow: async ({ configId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.runScoutNowFinished(configId)
                return
            }
            const config = values.scoutConfigs?.find((candidate) => candidate.id === configId)
            try {
                await signalsScoutConfigRun(String(teamId), configId)
                captureScoutAction({
                    actionType: 'run_now',
                    surface: 'scout_detail',
                    skillName: config?.skill_name ?? null,
                })
                lemonToast.success('Run started. It shows up in this scout’s runs when it finishes.')
                // The run row appears on the next poll; pull once now so the page reacts immediately.
                actions.loadScoutRuns()
            } catch (error: any) {
                // The endpoint refuses deliberately in several ordinary cases — already running,
                // over the daily budget — so the backend's own message is the useful one.
                lemonToast.error(error?.detail || error?.message || 'Could not start a run')
            } finally {
                actions.runScoutNowFinished(configId)
            }
        },
        updateScoutConfig: async ({ configId, updates }) => {
            const inFlight: Set<string> = (cache.updatingScoutIds ??= new Set())
            const pendingUpdates: Map<string, SignalScoutConfigUpdate> = (cache.pendingScoutConfigUpdates ??= new Map())

            if (inFlight.has(configId)) {
                actions.patchScoutConfigLocally(configId, updates)
                pendingUpdates.set(configId, { ...pendingUpdates.get(configId), ...updates })
                return
            }

            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.updateScoutConfigFinished(configId)
                return
            }

            let confirmedConfig = values.scoutConfigs?.find((config) => config.id === configId)
            let updatesToSend: SignalScoutConfigUpdate | undefined = updates
            let queuedUpdatesAfterFailure: SignalScoutConfigUpdate | undefined
            inFlight.add(configId)
            actions.patchScoutConfigLocally(configId, updates)

            try {
                while (updatesToSend) {
                    const previousCronSchedule = confirmedConfig?.run_cron_schedule
                    const previousConfig = confirmedConfig
                    const updated = await signalsScoutConfigUpdate(String(teamId), configId, updatesToSend)
                    captureScoutConfigUpdates(previousConfig, updatesToSend, true)
                    confirmedConfig = updated

                    if (updatesToSend.run_cron_schedule === null && previousCronSchedule) {
                        lemonToast.info('Scheduled run time cleared. The scout is back on its rolling interval.')
                    }

                    const queuedUpdates = pendingUpdates.get(configId)
                    if (!queuedUpdates) {
                        actions.patchScoutConfigLocally(configId, updated)
                        updatesToSend = undefined
                        continue
                    }

                    pendingUpdates.delete(configId)
                    // Keep queued optimistic changes visible while their follow-up request runs.
                    actions.patchScoutConfigLocally(configId, { ...updated, ...queuedUpdates })
                    updatesToSend = queuedUpdates
                }
            } catch (error: any) {
                queuedUpdatesAfterFailure = pendingUpdates.get(configId)
                if (updatesToSend) {
                    captureScoutConfigUpdates(confirmedConfig, updatesToSend, false)
                }
                if (confirmedConfig) {
                    actions.patchScoutConfigLocally(configId, confirmedConfig)
                }
                lemonToast.error(error?.detail || error?.message || 'Failed to update scout config')
            } finally {
                inFlight.delete(configId)
                pendingUpdates.delete(configId)
                actions.updateScoutConfigFinished(configId)
                if (queuedUpdatesAfterFailure) {
                    actions.updateScoutConfig(configId, queuedUpdatesAfterFailure)
                }
            }
        },
        deleteScout: async ({ configId, surface }) => {
            // The reducer above already flags this id, but that value is reactive (for the button)
            // and can't tell a fresh submit from a duplicate. The cache Set is the non-reactive guard:
            // a second submit while the first is in flight bails before issuing another request.
            const inFlight: Set<string> = (cache.deletingScoutIds ??= new Set())
            if (inFlight.has(configId)) {
                return
            }
            inFlight.add(configId)
            try {
                const config = values.scoutConfigs?.find((c) => c.id === configId)
                if (!config) {
                    return
                }
                const displayName = prettifyScoutSkillName(config.skill_name)
                // Scout skills are seeded under the canonical (parent/root) team, and the coordinator's
                // `register_missing_configs` only scans skill rows there — so archive against the canonical
                // project id, not the raw child-environment team id. Archiving the child team would 404 (the
                // skill lives on the parent), get swallowed as "already archived" below, and leave a live
                // skill the coordinator re-seeds. `currentProjectId` mirrors the backend `_canonical_team_id`
                // (parent_team_id or team_id); it's '@current' until the team loads, which we reject.
                const canonicalProjectId = teamLogic.values.currentProjectId
                try {
                    // Archiving the skill is the permanent off switch: the coordinator won't re-seed a
                    // tombstoned skill or re-create its config. Only custom scouts are deletable — the UI
                    // offers canonical ones disable instead, since a deleted canonical scout can't be re-added.
                    if (config.scout_origin === 'custom') {
                        // A custom scout's config must never be dropped without first archiving its skill —
                        // otherwise the coordinator re-seeds the config and the scout runs again. If the
                        // project can't be resolved to archive, fail here instead of half-deleting (the outer
                        // catch surfaces the error and reloads, leaving the row intact).
                        if (typeof canonicalProjectId !== 'number') {
                            throw new Error('Could not resolve the active project to archive the scout')
                        }
                        try {
                            await llmSkillsNameArchiveCreate(String(canonicalProjectId), config.skill_name)
                        } catch (error: any) {
                            // Already archived (e.g. retrying after a partial failure) — fall through to
                            // clear the leftover config rather than dead-ending on a 404.
                            if (error?.status !== 404) {
                                throw error
                            }
                        }
                    }
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        throw new Error('Could not resolve the active project')
                    }
                    await signalsScoutConfigDestroy(String(teamId), configId)
                    // Remove only after the backend confirms — deletion is irreversible, so no optimistic
                    // drop that would have to be re-inserted (and re-sorted) on failure.
                    actions.removeScoutConfigLocally(configId)
                    captureScoutAction({
                        actionType: 'delete_scout',
                        surface,
                        skillName: config.skill_name,
                        extra: { scout_origin: config.scout_origin, success: true },
                    })
                    lemonToast.success(`Deleted ${displayName}`)
                    // The scout's own page (and any finding deep link under it) has nothing left to show
                    // once it is gone.
                    const scoutPath = urls.inboxScout(config.skill_name)
                    const { pathname } = router.values.location
                    if (pathname.endsWith(scoutPath) || pathname.includes(`${scoutPath}/`)) {
                        router.actions.push(urls.inbox('scouts'))
                    }
                } catch (error: any) {
                    captureScoutAction({
                        actionType: 'delete_scout',
                        surface,
                        skillName: config.skill_name,
                        extra: { scout_origin: config.scout_origin, success: false },
                    })
                    lemonToast.error(error?.detail || error?.message || 'Failed to delete scout')
                    // A partial failure (skill archived but config delete failed) could desync the list
                    // from the backend — reload the truth so the row reflects reality.
                    actions.loadScoutConfigs()
                }
            } finally {
                inFlight.delete(configId)
                actions.deleteScoutFinished(configId)
            }
        },
        startScoutChatTask: async ({ chatType, taskLabel }) => {
            // Task-kickoff, mirroring inboxTaskKickoffLogic: start a cloud task from a fixed
            // template, then navigate to it. Not a live chat.
            // The CTAs carry this as a `disabledReason`; this backstops the paths that don't go
            // through a button press, since the endpoint enforces no consent of its own.
            if (values.aiConsentDisabledReason) {
                lemonToast.error(values.aiConsentDisabledReason)
                actions.startScoutChatTaskFailure()
                return
            }
            captureScoutChatStarted({ chatType, surface: 'fleet_list' })
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                actions.startScoutChatTaskFailure()
                return
            }
            try {
                // The server owns the prompt template, creates the task repo-less with the
                // reserved signals_chat origin (which exempts it from the Desktop access gate
                // on the task run endpoints) and starts its interactive run in one call.
                const task = await signalsScoutChatTasksCreate(String(teamId), { chat_type: chatType })
                actions.startScoutChatTaskSuccess()
                router.actions.push(urls.taskDetail(task.task_id))
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || `Failed to start ${taskLabel}`)
                actions.startScoutChatTaskFailure()
            }
        },
        startRunsPolling: () => {
            // Fetch once immediately, then a slow poll keeps "running now" + recent emissions
            // fresh. The keyed disposable is torn down on stopRunsPolling / unmount / tab hide.
            // The cheap findings summary rides the same cadence so the roster headline fills in on
            // its own fast query. The fleet list needs only the per-scout runs; the paginated
            // window is the findings page's own source and is polled there.
            //
            // Reference-counted: the roster stays mounted (hidden) under a scout page, and both
            // subscribe. Without the count the page's unmount would stop the roster's poll.
            cache.runsPollSubscribers = (cache.runsPollSubscribers ?? 0) + 1
            actions.loadScoutRuns()
            actions.loadFleetFindingsSummary()
            if (values.scoutMetadata === null) {
                actions.loadScoutMetadata()
            }
            if (cache.runsPollSubscribers > 1) {
                return
            }
            cache.disposables.add(() => {
                const interval = setInterval(() => {
                    actions.loadScoutRuns()
                    actions.loadFleetFindingsSummary()
                    // The coordinator stamps `last_run_at` on dispatch, and the next-run labels derive from
                    // it, so a page left open across a scheduled run would otherwise read "Due now" forever.
                    actions.loadScoutConfigs()
                }, RUNS_REFETCH_INTERVAL_MS)
                return () => clearInterval(interval)
            }, 'runsPoll')
        },
        stopRunsPolling: () => {
            cache.runsPollSubscribers = Math.max(0, (cache.runsPollSubscribers ?? 0) - 1)
            if (cache.runsPollSubscribers === 0) {
                cache.disposables.dispose('runsPoll')
            }
        },
    })),

    // Enabled and tag filters push, so Back and Forward step through them. Search is written by its
    // own debounced listener via `replace`, so it is not registered here.
    actionToUrl(({ values }) => {
        const toUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => [
            router.values.location.pathname,
            rosterFilterSearchParams(router.values.searchParams, rosterFilterUrlState(values)),
            router.values.hashParams,
            { replace: false },
        ]
        return {
            setScoutEnabledFilter: toUrl,
            setScoutTagFilter: toUrl,
        }
    }),

    urlToAction(({ actions, values }) => {
        const applyFromUrl = (
            _: unknown,
            searchParams: Record<string, any>,
            __: unknown,
            { method }: { method: 'PUSH' | 'REPLACE' | 'POP' }
        ): void => {
            const hasRosterParams =
                'scoutSearch' in searchParams || 'scoutEnabled' in searchParams || 'scoutTags' in searchParams
            if (!hasRosterParams) {
                // Back or Forward onto a bare roster URL asks for the default, unfiltered view: reset
                // the filters and leave the URL bare so a second Back can still reach the entries
                // beneath it. Reflecting the persisted filters back here would undo the navigation.
                if (method === 'POP') {
                    if (
                        values.scoutSearch !== '' ||
                        values.scoutEnabledFilter !== 'all' ||
                        values.selectedScoutTags.length > 0
                    ) {
                        actions.hydrateRosterFilters('', 'all', [])
                    }
                    return
                }
                // Only a fresh navigation reflects the persisted filters back, so the current view
                // is immediately shareable. A replace is not a navigation: a sibling inbox logic
                // replaces the bare URL to restore its own params while a Back is still being
                // handled, and writing the roster filters there would leave the URL filtered after
                // that Back resets the controls.
                if (method !== 'PUSH') {
                    return
                }
                const desired = rosterFilterSearchParams({}, rosterFilterUrlState(values))
                if (Object.keys(desired).length > 0) {
                    router.actions.replace(
                        router.values.location.pathname,
                        { ...router.values.searchParams, ...desired },
                        router.values.hashParams
                    )
                }
                return
            }
            // A shared link is authoritative: apply what it carries and reset the rest to defaults.
            // Guarded so plain navigation onto the roster does not re-dispatch an unchanged state.
            const parsed = parseRosterFilterSearchParams(searchParams)
            if (
                parsed.scoutSearch === values.scoutSearch &&
                parsed.scoutEnabledFilter === values.scoutEnabledFilter &&
                sameTags(parsed.selectedScoutTags, values.selectedScoutTags)
            ) {
                return
            }
            actions.hydrateRosterFilters(parsed.scoutSearch, parsed.scoutEnabledFilter, parsed.selectedScoutTags)
        }
        return {
            [urls.inbox('scouts')]: applyFromUrl,
        }
    }),

    events(({ actions }) => ({
        afterMount: () => {
            // Configs are cheap and the always-mounted setup widget needs them. The paginated
            // runs window is loaded + polled only while the fleet list is open (startRunsPolling).
            actions.setRosterEvaluatedAt(Date.now())
            actions.loadScoutConfigs()
        },
    })),
])
