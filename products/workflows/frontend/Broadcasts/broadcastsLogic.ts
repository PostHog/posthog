import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { loadAppMetricsTotals } from 'lib/components/AppMetrics/appMetricsLogic'
import { dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils/objects'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { TeamPublicType, TeamType } from '~/types'

import { hogFlowsBatchJobsList, hogFlowsList } from 'products/workflows/frontend/generated/api'
import type {
    HogFlowBatchJobApi,
    HogFlowMinimalApi,
    PaginatedHogFlowMinimalListApi,
} from 'products/workflows/frontend/generated/api.schemas'

export type BroadcastStatus = 'draft' | 'scheduled' | 'sending' | 'sent' | 'failed' | 'archived' | 'unknown'

export interface BroadcastRowDetails {
    latestBatchJob: HogFlowBatchJobApi | null
    /** Null until the run's metrics load, or when they fail to. */
    totals: Record<string, number> | null
}

/** Rows per page. Each row loads its latest run and metrics, so a page stays small enough to enrich. */
export const BROADCASTS_PAGE_SIZE = 30

export type BroadcastsStatusFilter = 'all' | 'draft' | 'active' | 'archived'
const BROADCASTS_STATUS_FILTERS: BroadcastsStatusFilter[] = ['all', 'draft', 'active', 'archived']

export interface BroadcastsFilters {
    search: string
    status: BroadcastsStatusFilter
    createdBy: string | null
    page: number
}

const DEFAULT_FILTERS: BroadcastsFilters = { search: '', status: 'all', createdBy: null, page: 1 }

/** Mirrors the list API's broadcast_eligible filter: a batch trigger, one email step, nothing else. */
export function isBroadcastShaped(
    actions: { type?: string; config?: { type?: string } }[] | null | undefined
): boolean {
    const steps = actions ?? []
    return (
        steps.some((step) => step.type === 'trigger' && step.config?.type === 'batch') &&
        steps.filter((step) => step.type === 'function_email').length === 1 &&
        steps.every((step) => ['trigger', 'function_email', 'exit'].includes(step.type ?? ''))
    )
}

const DEFAULT_RECIPIENT = '{{ person.properties.email }}'

type FlowStep = { id?: string; type?: string; config?: Record<string, any> }
type FlowEdge = { from?: string; to?: string }

/**
 * Whether the broadcast wizard can edit a broadcast-shaped workflow without misdescribing it. The
 * wizard only models a person audience sent to each person's own email along trigger, email, exit;
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
    const recipient = email[0].config?.inputs?.email?.value?.to?.email
    // Exactly trigger -> email -> exit: any other edge is a path the wizard cannot show, such as one
    // that skips the email.
    const paths = new Set((edges ?? []).map((edge) => `${edge.from}->${edge.to}`))
    return (
        trigger[0].config?.filters?.audience_type !== 'accounts' &&
        (!recipient || recipient === DEFAULT_RECIPIENT) &&
        paths.size === 2 &&
        paths.has(`${trigger[0].id}->${email[0].id}`) &&
        paths.has(`${email[0].id}->${exit[0].id}`)
    )
}

export function isEligibleWorkflow(flow: Pick<HogFlowMinimalApi, 'origin_product'>): boolean {
    return flow.origin_product !== 'broadcasts'
}

export function getBroadcastStatus(
    broadcast: HogFlowMinimalApi,
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
            return 'sent'
        }
        // Without this a failed or cancelled run falls through to the no-run fallback below, which
        // tells the sender another send is still pending when nothing is coming.
        return 'failed'
    }
    // Active with no batch job yet: it's waiting on its schedule (or a manual send).
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
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    broadcasts: PaginatedHogFlowMinimalListApi
    broadcastsLoading: boolean
    filters: BroadcastsFilters
    filtersPending: boolean
    hasLoadedBroadcasts: boolean
    rowDetailsById: Record<string, BroadcastRowDetails>
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface broadcastsLogicActions {
    clearRowDetails: (id: string) => {
        id: string
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
    setFilters: (filters: Partial<BroadcastsFilters>) => {
        filters: Partial<BroadcastsFilters>
    }
    setFiltersFromUrl: (filters: BroadcastsFilters) => {
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

export type broadcastsLogicType = MakeLogicType<broadcastsLogicValues, broadcastsLogicActions>

export const broadcastsLogic = kea<broadcastsLogicType>([
    path(['products', 'workflows', 'frontend', 'Broadcasts', 'broadcastsLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], teamLogic, ['currentTeam']],
    })),
    actions({
        loadBroadcasts: true,
        setFilters: (filters: Partial<BroadcastsFilters>) => ({ filters }),
        setFiltersFromUrl: (filters: BroadcastsFilters) => ({ filters }),
        setRowDetails: (id: string, details: BroadcastRowDetails) => ({ id, details }),
        clearRowDetails: (id: string) => ({ id }),
    }),
    loaders(({ values }) => ({
        broadcasts: [
            { results: [], count: 0 } as PaginatedHogFlowMinimalListApi,
            {
                loadBroadcasts: async (_, breakpoint) => {
                    if (!values.currentProjectId) {
                        return values.broadcasts
                    }
                    const response = await hogFlowsList(String(values.currentProjectId), {
                        // Broadcasts plus the ordinary workflows already shaped like one (a batch
                        // trigger and a single email), so existing sends show up here too.
                        broadcast_eligible: true,
                        search: values.filters.search || undefined,
                        status: values.filters.status !== 'all' ? values.filters.status : undefined,
                        created_by: values.filters.createdBy || undefined,
                        limit: BROADCASTS_PAGE_SIZE,
                        offset: (values.filters.page - 1) * BROADCASTS_PAGE_SIZE,
                    })
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers({
        rowDetailsById: [
            {} as Record<string, BroadcastRowDetails>,
            {
                setRowDetails: (state, { id, details }) => ({ ...state, [id]: details }),
                clearRowDetails: (state, { id }) => {
                    const { [id]: _, ...rest } = state
                    return rest
                },
            },
        ],
        // True between a filter change and the load it triggers, so the old rows don't read as results.
        filtersPending: [
            false,
            {
                setFilters: () => true,
                setFiltersFromUrl: () => true,
                loadBroadcastsSuccess: () => false,
                loadBroadcastsFailure: () => false,
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
            {
                // Any change other than the page itself starts the list over from the first page.
                setFilters: (state, { filters }) => ({ ...state, page: 1, ...filters }),
                setFiltersFromUrl: (_, { filters }) => filters,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
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
            for (const broadcast of broadcasts.results ?? []) {
                void (async () => {
                    let latestBatchJob: HogFlowBatchJobApi | null
                    try {
                        const batchJobs =
                            broadcast.status === 'draft'
                                ? ([] as HogFlowBatchJobApi[])
                                : await hogFlowsBatchJobsList(String(projectId), broadcast.id)
                        latestBatchJob = batchJobs[0] ?? null
                    } catch {
                        actions.clearRowDetails(broadcast.id)
                        return
                    }
                    actions.setRowDetails(broadcast.id, { latestBatchJob, totals: latestBatchJob ? null : {} })
                    if (!latestBatchJob) {
                        return
                    }
                    try {
                        const totals = await loadRunMetricTotals(latestBatchJob, values.currentTeam?.timezone ?? 'UTC')
                        actions.setRowDetails(broadcast.id, { latestBatchJob, totals })
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
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => {
            const { search, status, createdBy, page } = values.filters
            const searchParams = {
                ...router.values.searchParams,
                search: search || undefined,
                status: status !== 'all' ? status : undefined,
                created_by: createdBy || undefined,
                page: page > 1 ? page : undefined,
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.broadcasts()]: (_, searchParams) => {
            const status = searchParams['status']
            const parsed: BroadcastsFilters = {
                // The API rejects longer search terms.
                search: searchParams['search'] ? String(searchParams['search']).slice(0, 200) : '',
                status: BROADCASTS_STATUS_FILTERS.includes(status) ? status : 'all',
                createdBy: searchParams['created_by'] ? String(searchParams['created_by']) : null,
                page: Math.max(1, parseInt(String(searchParams['page'])) || 1),
            }
            if (!objectsEqual(parsed, values.filters)) {
                actions.setFiltersFromUrl(parsed)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadBroadcasts()
    }),
])
