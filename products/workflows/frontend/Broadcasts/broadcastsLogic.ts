import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { loadAppMetricsTotals } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { buildUserScopedPersistenceConfig } from 'lib/logic/persistence'
import { objectsEqual } from 'lib/utils/objects'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { TeamPublicType, TeamType } from '~/types'

import {
    hogFlowsBatchJobsList,
    hogFlowsBulkUpdateTagsCreate,
    hogFlowsList,
    hogFlowsSchedulesList,
} from 'products/workflows/frontend/generated/api'
import type {
    HogFlowApi,
    HogFlowBatchJobApi,
    HogFlowScheduleApi,
    PaginatedHogFlowMinimalListApi,
} from 'products/workflows/frontend/generated/api.schemas'

import {
    ManagedBroadcast,
    confirmArchiveBroadcast,
    confirmDeleteBroadcast,
    restoreBroadcast,
} from './broadcastLifecycle'

export type BroadcastStatus = 'draft' | 'scheduled' | 'sending' | 'sent' | 'failed' | 'archived' | 'unknown'

export interface BroadcastRowDetails {
    latestBatchJob: HogFlowBatchJobApi | null
    /** Null until the run's metrics load, or when they fail to. */
    totals: Record<string, number> | null
    /** Whether an active schedule has sends still to come. Unset when the schedules couldn't load. */
    hasPendingSchedule?: boolean
    /** Every run's status, newest first. An older run can still be sending after a newer one finished. */
    batchJobStatuses?: (string | null | undefined)[]
}

/** Rows per page. Each row loads its latest run and metrics, so a page stays small enough to enrich. */
export const BROADCASTS_PAGE_SIZE = 30

export type BroadcastsStatusFilter = 'all' | Exclude<BroadcastStatus, 'unknown'>
const BROADCASTS_STATUS_FILTERS: BroadcastsStatusFilter[] = [
    'all',
    'draft',
    'scheduled',
    'sending',
    'sent',
    'failed',
    'archived',
]

export interface BroadcastsFilters {
    search: string
    status: BroadcastsStatusFilter
    createdBy: string | null
    tags: string[]
    page: number
}

const DEFAULT_FILTERS: BroadcastsFilters = { search: '', status: 'all', createdBy: null, tags: [], page: 1 }

// The search params actionToUrl writes below. A URL that carries none of them states no filters at all,
// which is different from stating that every filter is off.
const FILTER_URL_PARAMS = ['search', 'status', 'created_by', 'tags', 'page']

type FlowStep = { id?: string; type?: string; config?: Record<string, any> }

/** Mirrors the list API's broadcast_eligible filter: a batch trigger, one email step, nothing else. */
export function isBroadcastShaped(actions: FlowStep[] | null | undefined): boolean {
    const steps = actions ?? []
    return (
        steps.some((step) => step.type === 'trigger' && step.config?.type === 'batch') &&
        steps.filter((step) => step.type === 'function_email').length === 1 &&
        steps.every((step) => ['trigger', 'function_email', 'exit'].includes(step.type ?? ''))
    )
}

type FlowEdge = { from?: string; to?: string }

/**
 * Whether the broadcast wizard can edit a broadcast-shaped workflow without misdescribing it. The
 * wizard only models a person audience along trigger, email, exit. Its Content step edits the email's
 * "To" like any other field, so a custom recipient is fine;
 * anything else opens as the read-only summary instead.
 */
export function canEditInWizard(actions: FlowStep[] | null | undefined, edges: FlowEdge[] | null | undefined): boolean {
    const steps = actions ?? []
    const [trigger, email, exit] = ['trigger', 'function_email', 'exit'].map((type) =>
        steps.filter((step) => step.type === type)
    )
    // One of each and nothing else, so the steps the wizard edits are the only ones there are.
    if (steps.length !== 3 || trigger.length !== 1 || email.length !== 1 || exit.length !== 1) {
        return false
    }
    // Exactly trigger -> email -> exit: any other edge is a path the wizard cannot show, such as one
    // that skips the email.
    const paths = new Set((edges ?? []).map((edge) => `${edge.from}->${edge.to}`))
    return (
        trigger[0].config?.filters?.audience_type !== 'accounts' &&
        paths.size === 2 &&
        paths.has(`${trigger[0].id}->${email[0].id}`) &&
        paths.has(`${email[0].id}->${exit[0].id}`)
    )
}

/** Null batch jobs means they haven't loaded, so whether a send is running is still unknown. */
export interface StoppableBroadcast {
    status?: HogFlowApi['status']
    actions?: FlowStep[] | null
    edges?: FlowEdge[] | null
    schedules?: Pick<HogFlowScheduleApi, 'status'>[]
}

export function canMoveToDraft(
    broadcast: StoppableBroadcast | null,
    batchJobs: Pick<HogFlowBatchJobApi, 'status'>[] | null
): boolean {
    const schedules = broadcast?.schedules ?? []
    const neverSent = batchJobs?.length === 0
    return (
        broadcast?.status === 'active' &&
        // Only a send still to come can be stopped, since relaunching one that went out resends it. The
        // wizard models a single schedule, so a relaunch would fold several into one. A launch or a
        // one-time schedule that never started a run sent nothing, so it can go back to draft too.
        schedules.length <= 1 &&
        (neverSent || (schedules.length === 1 && schedules[0].status !== 'completed')) &&
        batchJobs !== null &&
        !batchJobs.some((job) => ['waiting', 'queued', 'active'].includes(job.status ?? '')) &&
        // Even a broadcast's own graph can be edited elsewhere, and the wizard would save over it.
        canEditInWizard(broadcast.actions, broadcast.edges)
    )
}

export function getBroadcastStatus(
    broadcast: { status?: string | null; origin_product?: string | null },
    details: BroadcastRowDetails | undefined
): BroadcastStatus {
    if (broadcast.status === 'draft') {
        return 'draft'
    }
    if (broadcast.status === 'archived') {
        return 'archived'
    }
    if (!details) {
        return 'unknown'
    }
    const latestJob = details.latestBatchJob
    if (latestJob) {
        if (['waiting', 'queued', 'active'].includes(latestJob.status ?? '')) {
            return 'sending'
        }
        if (latestJob.status === 'completed') {
            // A recurring broadcast between runs has more to send. A failed run still reads as failed.
            if (details.hasPendingSchedule === undefined) {
                return 'unknown'
            }
            return details.hasPendingSchedule ? 'scheduled' : 'sent'
        }
        // Without this a failed or cancelled run falls through to the no-run fallback below, which
        // tells the sender another send is still pending when nothing is coming.
        return 'failed'
    }
    // Live with no run and nothing scheduled: a launch from the wizard that never finished, so nothing
    // will ever send. A workflow opened here can wait for a send started through the API instead.
    if (details.hasPendingSchedule === false && broadcast.origin_product === 'broadcasts') {
        return 'failed'
    }
    // Active with no batch job yet: it's waiting on its schedule.
    return 'scheduled'
}

// A batch send's email metrics are recorded against the batch job, not the flow, so the row counts
// come from the latest run rather than the flow-scoped totals endpoint.
async function loadRunMetricTotals(job: HogFlowBatchJobApi, timezone: string): Promise<Record<string, number>> {
    const created = dayjs(job.created_at)
    const response = await loadAppMetricsTotals(
        {
            appSource: 'hog_flow',
            appSourceId: job.id,
            breakdownBy: ['metric_name'],
            dateFrom: created.subtract(1, 'hour').toISOString(),
            dateTo: dayjs().add(1, 'hour').toISOString(),
        },
        timezone
    )
    return Object.fromEntries(Object.entries(response).map(([metricName, { total }]) => [metricName, total]))
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastsLogicValues {
    currentProjectId: number | null // projectLogic
    tags: string[] // tagsModel
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    broadcasts: PaginatedHogFlowMinimalListApi
    broadcastsLoading: boolean
    filters: BroadcastsFilters
    filtersPending: boolean
    hasLoadedBroadcasts: boolean
    listGeneration: number
    loadFailed: boolean
    loadedFilters: BroadcastsFilters | null
    rowDetailsById: Record<string, BroadcastRowDetails>
    savingTagsFor: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastsLogicActions {
    loadTags: () => {
        value: true
    } // tagsModel
    loadTagsIfNeeded: () => {
        value: true
    } // tagsModel
    archiveBroadcast: (broadcast: ManagedBroadcast) => {
        broadcast: ManagedBroadcast
    }
    broadcastTagsChanged: (
        id: string,
        tags: string[]
    ) => {
        id: string
        tags: string[]
    }
    broadcastTagsSaved: (
        id: string,
        tags: string[] | null
    ) => {
        id: string
        tags: string[] | null
    }
    clearRowDetails: (id: string) => {
        id: string
    }
    deleteBroadcast: (broadcast: ManagedBroadcast) => {
        broadcast: ManagedBroadcast
    }
    loadBroadcasts: () => {
        value: true
    }
    loadBroadcastsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBroadcastsSuccess: (
        broadcasts: PaginatedHogFlowMinimalListApi,
        payload?: {
            value: true
        }
    ) => {
        broadcasts: PaginatedHogFlowMinimalListApi
        payload?: {
            value: true
        }
    }
    restoreBroadcast: (broadcast: ManagedBroadcast) => {
        broadcast: ManagedBroadcast
    }
    saveBroadcastTags: (
        id: string,
        tags: string[]
    ) => {
        id: string
        tags: string[]
    }
    setFilters: (filters: Partial<BroadcastsFilters>) => {
        filters: Partial<BroadcastsFilters>
    }
    setFiltersFromUrl: (filters: BroadcastsFilters) => {
        filters: BroadcastsFilters
    }
    setLoadedFilters: (filters: BroadcastsFilters) => {
        filters: BroadcastsFilters
    }
    setRowDetails: (
        id: string,
        details: BroadcastRowDetails
    ) => {
        details: BroadcastRowDetails
        id: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        filtersPending: (filters: BroadcastsFilters, loadedFilters: BroadcastsFilters | null) => boolean
    }
}

export type broadcastsLogicType = MakeLogicType<
    broadcastsLogicValues,
    broadcastsLogicActions,
    Record<string, any>,
    broadcastsLogicMeta
>

export const broadcastsLogic = kea<broadcastsLogicType>([
    path(['products', 'workflows', 'frontend', 'Broadcasts', 'broadcastsLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], teamLogic, ['currentTeam'], tagsModel, ['tags']],
        actions: [tagsModel, ['loadTags', 'loadTagsIfNeeded']],
    })),
    actions({
        loadBroadcasts: true,
        setFilters: (filters: Partial<BroadcastsFilters>) => ({ filters }),
        setFiltersFromUrl: (filters: BroadcastsFilters) => ({ filters }),
        setRowDetails: (id: string, details: BroadcastRowDetails) => ({ id, details }),
        clearRowDetails: (id: string) => ({ id }),
        setLoadedFilters: (filters: BroadcastsFilters) => ({ filters }),
        saveBroadcastTags: (id: string, tags: string[]) => ({ id, tags }),
        broadcastTagsChanged: (id: string, tags: string[]) => ({ id, tags }),
        broadcastTagsSaved: (id: string, tags: string[] | null) => ({ id, tags }),
        archiveBroadcast: (broadcast: ManagedBroadcast) => ({ broadcast }),
        restoreBroadcast: (broadcast: ManagedBroadcast) => ({ broadcast }),
        deleteBroadcast: (broadcast: ManagedBroadcast) => ({ broadcast }),
    }),
    loaders(({ actions, values }) => ({
        broadcasts: [
            { results: [], count: 0 } as PaginatedHogFlowMinimalListApi,
            {
                loadBroadcasts: async (_, breakpoint) => {
                    if (!values.currentProjectId) {
                        return values.broadcasts
                    }
                    const requested = values.filters
                    const response = await hogFlowsList(String(values.currentProjectId), {
                        // Only broadcasts. A workflow shaped like one stays under workflows until someone moves it.
                        type: 'broadcast',
                        search: values.filters.search || undefined,
                        broadcast_status: values.filters.status !== 'all' ? values.filters.status : undefined,
                        created_by: values.filters.createdBy || undefined,
                        tags: values.filters.tags.length ? JSON.stringify(values.filters.tags) : undefined,
                        limit: BROADCASTS_PAGE_SIZE,
                        offset: (values.filters.page - 1) * BROADCASTS_PAGE_SIZE,
                    })
                    breakpoint()
                    actions.setLoadedFilters(requested)
                    return response
                },
            },
        ],
    })),
    reducers(() => ({
        broadcasts: [
            { results: [], count: 0 } as PaginatedHogFlowMinimalListApi,
            {
                broadcastTagsChanged: (state, { id, tags }) => ({
                    ...state,
                    results: (state.results ?? []).map((broadcast) =>
                        broadcast.id === id ? { ...broadcast, tags } : broadcast
                    ),
                }),
                // A failed save passes null, which leaves the row as it is until the reload lands.
                broadcastTagsSaved: (state, { id, tags }) =>
                    tags === null
                        ? state
                        : {
                              ...state,
                              results: (state.results ?? []).map((broadcast) =>
                                  broadcast.id === id ? { ...broadcast, tags } : broadcast
                              ),
                          },
            },
        ],
        // Which row's tags are in flight, so only that row's editor shows a spinner.
        savingTagsFor: [
            null as string | null,
            {
                saveBroadcastTags: (_, { id }) => id,
                broadcastTagsSaved: () => null,
            },
        ],
        rowDetailsById: [
            {} as Record<string, BroadcastRowDetails>,
            {
                setRowDetails: (state, { id, details }) => ({ ...state, [id]: details }),
                // A send can start between loads, so the run statuses that gate Archive are refetched with the
                // list. The status tags and counts stay on screen until then.
                loadBroadcasts: (state) =>
                    Object.fromEntries(
                        Object.entries(state).map(([id, { batchJobStatuses: _, ...details }]) => [id, details])
                    ),
                clearRowDetails: (state, { id }) => {
                    const { [id]: _, ...rest } = state
                    return rest
                },
            },
        ],
        // The filters the shown rows were loaded for, so rows from other filters never read as results.
        loadedFilters: [
            null as BroadcastsFilters | null,
            {
                setLoadedFilters: (_, { filters }) => filters,
            },
        ],
        loadFailed: [
            false,
            {
                loadBroadcasts: () => false,
                loadBroadcastsFailure: () => true,
            },
        ],
        // Bumped per list load, so a slow row lookup from an earlier load can't change a newer one's rows.
        listGeneration: [
            0,
            {
                loadBroadcastsSuccess: (state) => state + 1,
            },
        ],
        hasLoadedBroadcasts: [
            false as boolean,
            {
                loadBroadcastsSuccess: () => true,
            },
        ],
        filters: [
            DEFAULT_FILTERS,
            // The list unmounts when a broadcast opens, so the filters are persisted to survive that and
            // be restored when the user comes back to the list. The key carries the user and the team, so
            // another account or another project never reads these filters.
            buildUserScopedPersistenceConfig('broadcasts_list_filters__'),
            {
                // Any change other than the page itself starts the list over from the first page.
                setFilters: (state, { filters }) => ({ ...state, page: 1, ...filters }),
                setFiltersFromUrl: (_, { filters }) => filters,
            },
        ],
    })),
    selectors({
        filtersPending: [
            (s) => [s.filters, s.loadedFilters],
            (filters: BroadcastsFilters, loadedFilters: BroadcastsFilters | null): boolean =>
                !objectsEqual(filters, loadedFilters),
        ],
    }),
    listeners(({ actions, values }) => ({
        // Each change moves the row between status filters, so the page reloads rather than patching the row.
        archiveBroadcast: ({ broadcast }) => {
            if (values.currentProjectId) {
                confirmArchiveBroadcast(String(values.currentProjectId), broadcast, actions.loadBroadcasts)
            }
        },
        restoreBroadcast: async ({ broadcast }) => {
            if (values.currentProjectId) {
                await restoreBroadcast(String(values.currentProjectId), broadcast, actions.loadBroadcasts)
            }
        },
        deleteBroadcast: ({ broadcast }) => {
            if (values.currentProjectId) {
                confirmDeleteBroadcast(String(values.currentProjectId), broadcast, actions.loadBroadcasts)
            }
        },
        loadBroadcastsSuccess: ({ broadcasts }) => {
            const projectId = values.currentProjectId
            if (!projectId) {
                return
            }
            // A page past the end (a stale link, or rows removed since) would show an empty table with
            // no way back, so land on the last real page.
            const lastPage = Math.max(1, Math.ceil(broadcasts.count / BROADCASTS_PAGE_SIZE))
            if (values.filters.page > lastPage) {
                actions.setFilters({ page: lastPage })
                return
            }
            // Best-effort per-row enrichment: batch jobs decide the status chip, metric totals fill
            // the engagement counts. The run is stored before its metrics load, so a slow or failed
            // metrics query can't leave the status unknown.
            const generation = values.listGeneration
            const isCurrent = (): boolean => values.listGeneration === generation
            for (const broadcast of broadcasts.results ?? []) {
                void (async () => {
                    let latestBatchJob: HogFlowBatchJobApi | null
                    let batchJobStatuses: (string | null | undefined)[]
                    let hasPendingSchedule: boolean | undefined
                    try {
                        // The list rows carry no schedules, and a recurring broadcast between runs needs them
                        // to read as scheduled. A failed schedules request only loses that distinction.
                        const [batchJobs, schedules] =
                            broadcast.status === 'draft'
                                ? [[] as HogFlowBatchJobApi[], undefined]
                                : await Promise.all([
                                      hogFlowsBatchJobsList(String(projectId), broadcast.id),
                                      hogFlowsSchedulesList(String(projectId), broadcast.id).catch(() => undefined),
                                  ])
                        latestBatchJob = batchJobs[0] ?? null
                        batchJobStatuses = batchJobs.map((job) => job.status)
                        hasPendingSchedule = schedules?.some((schedule) => schedule.status === 'active')
                    } catch {
                        if (isCurrent()) {
                            actions.clearRowDetails(broadcast.id)
                        }
                        return
                    }
                    if (!isCurrent()) {
                        return
                    }
                    actions.setRowDetails(broadcast.id, {
                        latestBatchJob,
                        totals: latestBatchJob ? null : {},
                        hasPendingSchedule,
                        batchJobStatuses,
                    })
                    if (!latestBatchJob) {
                        return
                    }
                    try {
                        const totals = await loadRunMetricTotals(latestBatchJob, values.currentTeam?.timezone ?? 'UTC')
                        if (isCurrent()) {
                            actions.setRowDetails(broadcast.id, {
                                latestBatchJob,
                                totals,
                                hasPendingSchedule,
                                batchJobStatuses,
                            })
                        }
                    } catch {
                        // The counts stay unknown; the status already rendered from the run.
                    }
                })()
            }
        },
        setFilters: async (_, breakpoint) => {
            // Debounce so typing in the search box doesn't fire a request per keystroke.
            await breakpoint(300)
            actions.loadBroadcasts()
        },
        setFiltersFromUrl: () => {
            actions.loadBroadcasts()
        },
        loadBroadcastsFailure: () => {
            lemonToast.error("Couldn't load broadcasts. Refresh the page to try again.")
        },
        saveBroadcastTags: async ({ id, tags }, breakpoint) => {
            const projectId = values.currentProjectId
            if (!projectId) {
                return
            }
            // The editor builds each payload from the row's tags, so a second edit made while the first
            // is in flight would be built from the stored list and drop the first one. Showing the new
            // tags at once gives that second edit the right starting point.
            actions.broadcastTagsChanged(id, tags)
            // One save per tag added or removed, so a burst of clicks is collapsed into a single write.
            await breakpoint(300)
            try {
                const response = await hogFlowsBulkUpdateTagsCreate(String(projectId), {
                    ids: [id],
                    action: 'set',
                    tags,
                })
                const updated = response.updated[0]
                if (!updated) {
                    throw new Error(response.skipped[0]?.reason ?? "You don't have access to edit this broadcast.")
                }
                actions.broadcastTagsSaved(id, updated.tags)
                // A new tag has to reach the project's tag list before the filter can offer it.
                tagsModel.findMounted()?.actions.loadTags()
                // The edit can move the row out of a tag filter, and the count with it, so the page is
                // reloaded rather than left showing a broadcast that no longer matches.
                if (values.filters.tags.length) {
                    actions.loadBroadcasts()
                }
            } catch (error: any) {
                actions.broadcastTagsSaved(id, null)
                lemonToast.error(`Couldn't save tags: ${error?.detail || error?.message || 'unknown error'}`)
                // The row is showing tags that were never stored, so the stored ones are read back.
                actions.loadBroadcasts()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => {
            const { search, status, createdBy, tags, page } = values.filters
            const searchParams = {
                ...router.values.searchParams,
                search: search || undefined,
                status: status !== 'all' ? status : undefined,
                created_by: createdBy || undefined,
                tags: tags.length ? tags : undefined,
                page: page > 1 ? page : undefined,
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.broadcasts()]: (_, searchParams) => {
            // An in-app link back to the list, such as the breadcrumb out of a broadcast, carries no filter
            // params. Parsing that URL would clear every filter, so the filters held in state are restored
            // and written back into the URL instead.
            if (!FILTER_URL_PARAMS.some((param) => param in searchParams)) {
                if (!objectsEqual(values.filters, DEFAULT_FILTERS)) {
                    actions.setFilters(values.filters)
                }
                return
            }
            const status = searchParams['status']
            const rawTags = searchParams['tags']
            const parsed: BroadcastsFilters = {
                // The API rejects longer search terms.
                search: searchParams['search'] ? String(searchParams['search']).slice(0, 200) : '',
                status: BROADCASTS_STATUS_FILTERS.includes(status) ? status : 'all',
                createdBy: searchParams['created_by'] ? String(searchParams['created_by']) : null,
                // kea-router parses a JSON array in the URL back into an array.
                tags: Array.isArray(rawTags)
                    ? rawTags.map(String)
                    : typeof rawTags === 'string' && rawTags
                      ? [rawTags]
                      : [],
                page: Math.max(1, parseInt(String(searchParams['page'])) || 1),
            }
            if (!objectsEqual(parsed, values.filters)) {
                actions.setFiltersFromUrl(parsed)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBroadcasts()
        actions.loadTagsIfNeeded()
    }),
])
