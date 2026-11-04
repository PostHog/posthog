import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    listeners,
    path,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { buildUserScopedPersistenceConfig } from 'lib/logic/persistence'
import { isUUIDLike } from 'lib/utils/guards'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import type { FileSystemEntry } from '~/queries/schema/schema-general'
import type { UserType } from '~/types'

import {
    hogFlowsCreate,
    hogFlowsMetricsGlobalRetrieve,
    hogFlowsRetrieve,
    hogFlowsSummariesList,
} from 'products/workflows/frontend/generated/api'
import type {
    HogFlowListSummaryApi,
    PaginatedHogFlowListSummaryListApi,
    WorkflowStatsRowApi,
} from 'products/workflows/frontend/generated/api.schemas'

import { prepareWorkflowDuplicate } from '../workflowDuplication'
import {
    confirmArchiveWorkflow,
    confirmDeleteWorkflow,
    restoreWorkflowToDraft,
    setWorkflowStatus,
    WorkflowRowAction,
    workflowActionErrorDetail,
} from '../workflowRowActions'
import type { WorkflowTemplateTypeFilter } from '../workflowTypeFilters'
import {
    FacetDefinition,
    FacetFilter,
    FacetSearchValue,
    MatchesText,
    createFacetMatcher,
    parseFacetQuery,
    serializeFacetQuery,
} from './FacetSearchBar/facetQuery'
import { buildWorkflowListFacets, matchesWorkflowListText } from './workflowListFacets'
import {
    LIST_TYPES,
    DEFAULT_COLUMNS,
    OPTIONAL_COLUMNS,
    OptionalColumn,
    STATUS_LABELS,
    TRIGGER_LABELS,
    TYPE_LABELS,
} from './workflowListLabels'
import { WorkflowListRow, buildWorkflowListRows } from './workflowListRows'

const WORKFLOWS_PAGE_TYPES = LIST_TYPES.join(',')
const PAGE_LIMIT = 500
const MIN_SERVER_SEARCH_LENGTH = 3
const SERVER_SEARCH_DEBOUNCE_MS = 300

export interface ServerSearchResult {
    text: string
    ids: string[]
    failed: boolean
}

/** `pending` while a server search for the current text is debouncing or in flight. */
export type ServerSearchStatus = 'off' | 'pending' | 'done' | 'failed'

const EMPTY_VALUE: FacetSearchValue = { filters: [], text: '' }
/** The flag-off list's single-value params, and the facet each one becomes. */
const LEGACY_FACET_PARAMS: { param: string; facet: string; isValid: (value: string) => boolean }[] = [
    { param: 'status', facet: 'status', isValid: (value) => value in STATUS_LABELS },
    { param: 'type', facet: 'kind', isValid: (value) => value in TYPE_LABELS },
    { param: 'trigger_type', facet: 'trigger', isValid: (value) => value in TRIGGER_LABELS },
    { param: 'created_by', facet: 'createdBy', isValid: isUUIDLike },
]
const LEGACY_PARAMS = [...LEGACY_FACET_PARAMS.map(({ param }) => param), 'tags', 'search', 'page']

// Parsing only needs facet keys and aliases, which don't depend on the loaded rows.
const QUERY_FACETS = buildWorkflowListFacets([])

function nextOffsetOf(page: PaginatedHogFlowListSummaryListApi): number | null {
    const nextOffset = page.next ? new URL(page.next, window.location.origin).searchParams.get('offset') : null
    return nextOffset && page.results.length ? Number(nextOffset) : null
}

/**
 * Follows `next` to the end, one page after another, so a row created mid-load still lands on a later
 * page. Rows are keyed by id, because that row shifts later offsets and repeats one.
 */
async function loadAllPages(
    fetchPage: (offset: number | undefined) => Promise<PaginatedHogFlowListSummaryListApi>
): Promise<HogFlowListSummaryApi[]> {
    const byId = new Map<string, HogFlowListSummaryApi>()
    let offset = 0
    let page = await fetchPage(undefined)
    for (;;) {
        for (const row of page.results) {
            byId.set(row.id, byId.get(row.id) ?? row)
        }
        const nextOffset = nextOffsetOf(page)
        if (nextOffset === null) {
            return [...byId.values()]
        }
        if (!(nextOffset > offset)) {
            throw new Error(
                `Loading stopped after ${byId.size} workflows because the server kept sending the same page. Try again.`
            )
        }
        offset = nextOffset
        page = await fetchPage(offset)
    }
}

function loadErrorDetailOf(error: string, errorObject: unknown): string {
    const failure = errorObject as { status?: number; detail?: string; message?: string } | undefined
    if (failure?.status === 403) {
        return 'You need at least viewer access to workflows in this project. Ask a project admin for it.'
    }
    return failure?.detail || failure?.message || error
}

/** Reads a param as written. kea-router turns number-like values such as `007` into numbers. */
function rawSearchParam(name: string): string {
    return new URLSearchParams(router.values.location.search).get(name) ?? ''
}

type RowChange = { id: string; patch: Partial<HogFlowListSummaryApi> } | { id: string; removed: true }

function applyRowChange(workflows: HogFlowListSummaryApi[], change: RowChange): HogFlowListSummaryApi[] {
    if ('removed' in change) {
        return workflows.filter((workflow) => workflow.id !== change.id)
    }
    return workflows.map((workflow) => (workflow.id === change.id ? { ...workflow, ...change.patch } : workflow))
}

function withFacetParams(searchParams: Record<string, unknown>, value: FacetSearchValue): Record<string, unknown> {
    const next: Record<string, unknown> = { ...searchParams }
    delete next.q
    delete next.text
    const q = serializeFacetQuery(value.filters)
    const text = value.text.trim()
    if (q) {
        next.q = q
    }
    if (text) {
        next.text = text
    }
    return next
}

/** Reads the filter params the flag-off list writes, so bookmarked links keep working. */
function legacyParamsToValue(searchParams: Record<string, unknown>): FacetSearchValue {
    const filters: FacetFilter[] = []
    for (const { param, facet, isValid } of LEGACY_FACET_PARAMS) {
        const raw = searchParams[param]
        const value = raw === undefined || raw === null ? '' : String(raw)
        if (value && isValid(value)) {
            filters.push({ facet, value, negated: false })
        }
    }
    for (const tag of legacyTagsOf(searchParams.tags)) {
        filters.push({ facet: 'tag', value: tag, negated: false })
    }
    return { filters, text: rawSearchParam('search') }
}

/** The flag-off list writes tags as a JSON list, which kea-router has usually parsed already. */
function legacyTagsOf(raw: unknown): string[] {
    const parsed = typeof raw === 'string' ? parseJsonOr(raw, [raw]) : raw
    return Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []
}

function parseJsonOr(raw: string, fallback: unknown): unknown {
    try {
        return JSON.parse(raw)
    } catch {
        return fallback
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowsListV2LogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    itemsByRef: Record<string, FileSystemEntry> // projectTreeDataLogic
    currentTeamId: number | null // teamLogic
    user: UserType | null // userLogic
    facets: FacetDefinition<WorkflowListRow>[]
    filteredRows: WorkflowListRow[]
    hasHealthFilter: boolean
    isUnfilteredAutomationView: boolean
    listLoaded: boolean
    loadErrorDetail: string | null
    loadFailed: boolean
    matchesText: MatchesText<WorkflowListRow>
    metrics: WorkflowStatsRowApi[] | null
    metricsLoaded: boolean
    metricsLoading: boolean
    pendingRowActions: Record<string, WorkflowRowAction>
    projectFilesEnabled: boolean
    requestedSearchText: string | null
    rows: WorkflowListRow[]
    serverSearch: ServerSearchResult | null
    serverSearchLoading: boolean
    serverSearchStatus: ServerSearchStatus
    shownColumns: OptionalColumn[]
    templateTypeFilter: WorkflowTemplateTypeFilter
    value: FacetSearchValue
    visibleColumns: OptionalColumn[]
    workflows: HogFlowListSummaryApi[] | null
    workflowsLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowsListV2LogicActions {
    archiveWorkflow: (row: WorkflowListRow) => {
        row: WorkflowListRow
    }
    clearFilters: () => {
        value: true
    }
    deleteWorkflow: (row: WorkflowListRow) => {
        row: WorkflowListRow
    }
    duplicateWorkflow: (row: WorkflowListRow) => {
        row: WorkflowListRow
    }
    loadMetrics: () => {
        value: true
    }
    loadMetricsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMetricsSuccess: (
        metrics: WorkflowStatsRowApi[] | null,
        payload?: {
            value: true
        }
    ) => {
        metrics: WorkflowStatsRowApi[] | null
        payload?: {
            value: true
        }
    }
    loadWorkflows: () => {
        value: true
    }
    loadWorkflowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadWorkflowsSuccess: (
        workflows: HogFlowListSummaryApi[],
        payload?: {
            value: true
        }
    ) => {
        workflows: HogFlowListSummaryApi[]
        payload?: {
            value: true
        }
    }
    patchWorkflow: (
        id: string,
        patch: Partial<HogFlowListSummaryApi>
    ) => {
        id: string
        patch: Partial<HogFlowListSummaryApi>
    }
    refreshWorkflows: () => {
        value: true
    }
    removeWorkflow: (id: string) => {
        id: string
    }
    resetColumns: () => {
        value: true
    }
    restoreWorkflow: (row: WorkflowListRow) => {
        row: WorkflowListRow
    }
    searchWorkflows: (text: string) => string
    searchWorkflowsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    searchWorkflowsSuccess: (
        serverSearch: ServerSearchResult | null,
        payload?: string
    ) => {
        serverSearch: ServerSearchResult | null
        payload?: string
    }
    setRowActionPending: (
        id: string,
        action: WorkflowRowAction | null
    ) => {
        action: WorkflowRowAction | null
        id: string
    }
    setValue: (value: FacetSearchValue) => {
        value: FacetSearchValue
    }
    toggleColumn: (column: OptionalColumn) => {
        column: 'created_by' | 'health' | 'last_7_days' | 'owner' | 'trigger' | 'type'
    }
    toggleWorkflowStatus: (row: WorkflowListRow) => {
        row: WorkflowListRow
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowsListV2LogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        hasHealthFilter: (value: FacetSearchValue) => boolean
        metricsLoaded: (metrics: WorkflowStatsRowApi[] | null) => boolean
        isUnfilteredAutomationView: (value: FacetSearchValue) => boolean
        templateTypeFilter: (value: FacetSearchValue) => WorkflowTemplateTypeFilter
        projectFilesEnabled: (featureFlags: FeatureFlagsSet) => boolean
        rows: (workflows: HogFlowListSummaryApi[] | null, metrics: WorkflowStatsRowApi[] | null) => WorkflowListRow[]
        listLoaded: (workflows: HogFlowListSummaryApi[] | null) => boolean
        facets: (
            rows: WorkflowListRow[],
            itemsByRef: Record<string, FileSystemEntry>,
            projectFilesEnabled: boolean,
            value: FacetSearchValue,
            user: UserType | null
        ) => FacetDefinition<WorkflowListRow>[]
        matchesText: (serverSearch: ServerSearchResult | null) => MatchesText<WorkflowListRow>
        serverSearchStatus: (value: FacetSearchValue, serverSearch: ServerSearchResult | null) => ServerSearchStatus
        filteredRows: (
            rows: WorkflowListRow[],
            value: FacetSearchValue,
            facets: FacetDefinition<WorkflowListRow>[],
            matchesText: MatchesText<WorkflowListRow>
        ) => WorkflowListRow[]
        shownColumns: (
            visibleColumns: ('created_by' | 'health' | 'last_7_days' | 'owner' | 'trigger' | 'type')[]
        ) => OptionalColumn[]
    }
}

export type workflowsListV2LogicType = MakeLogicType<
    workflowsListV2LogicValues,
    workflowsListV2LogicActions,
    Record<string, any>,
    workflowsListV2LogicMeta
>

export const workflowsListV2Logic = kea<workflowsListV2LogicType>([
    path(['products', 'workflows', 'frontend', 'workflowsListV2Logic']),
    // `hog_flows` is looked up by team, and a child environment's team id differs from its project id.
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeamId'],
            userLogic,
            ['user'],
            projectTreeDataLogic,
            ['itemsByRef'],
        ],
    })),
    actions({
        loadWorkflows: true,
        /** Reloads the rows and the server search, for workflows created outside this list. */
        refreshWorkflows: true,
        loadMetrics: true,
        setValue: (value: FacetSearchValue) => ({ value }),
        clearFilters: true,
        toggleColumn: (column: OptionalColumn) => ({ column }),
        resetColumns: true,
        patchWorkflow: (id: string, patch: Partial<HogFlowListSummaryApi>) => ({ id, patch }),
        removeWorkflow: (id: string) => ({ id }),
        setRowActionPending: (id: string, action: WorkflowRowAction | null) => ({ id, action }),
        toggleWorkflowStatus: (row: WorkflowListRow) => ({ row }),
        duplicateWorkflow: (row: WorkflowListRow) => ({ row }),
        archiveWorkflow: (row: WorkflowListRow) => ({ row }),
        restoreWorkflow: (row: WorkflowListRow) => ({ row }),
        deleteWorkflow: (row: WorkflowListRow) => ({ row }),
    }),
    loaders(({ values, cache }) => ({
        workflows: [
            null as HogFlowListSummaryApi[] | null,
            {
                loadWorkflows: async (_, breakpoint) => {
                    const teamId = String(values.currentTeamId)
                    // A row action that lands while the pages load is newer than what the server sent.
                    const changes: RowChange[] = []
                    cache.rowChangesDuringLoad = changes
                    const workflows = await loadAllPages((offset) => {
                        // Stops paging once a newer load starts or the list closes.
                        breakpoint()
                        return hogFlowsSummariesList(teamId, { type: WORKFLOWS_PAGE_TYPES, limit: PAGE_LIMIT, offset })
                    })
                    breakpoint()
                    return changes.reduce(applyRowChange, workflows)
                },
            },
        ],
        metrics: [
            null as WorkflowStatsRowApi[] | null,
            {
                loadMetrics: async (_, breakpoint) => {
                    try {
                        const metrics = await hogFlowsMetricsGlobalRetrieve(String(values.currentTeamId), {
                            after: '-7d',
                        })
                        breakpoint()
                        return metrics
                    } catch {
                        breakpoint()
                        // The list works without metrics, so a failure shows "Unavailable" in the
                        // metrics columns instead of an error toast.
                        return null
                    }
                },
            },
        ],
        serverSearch: [
            null as ServerSearchResult | null,
            {
                searchWorkflows: async (text: string, breakpoint): Promise<ServerSearchResult | null> => {
                    await breakpoint(SERVER_SEARCH_DEBOUNCE_MS)
                    if (values.requestedSearchText !== text) {
                        return values.serverSearch
                    }
                    cache.searchAbort?.abort()
                    const controller = new AbortController()
                    cache.searchAbort = controller
                    const teamId = String(values.currentTeamId)
                    try {
                        const workflows = await loadAllPages((offset) =>
                            hogFlowsSummariesList(
                                teamId,
                                { type: WORKFLOWS_PAGE_TYPES, search: text, limit: PAGE_LIMIT, offset },
                                { signal: controller.signal }
                            )
                        )
                        breakpoint()
                        return { text, ids: workflows.map((workflow) => workflow.id), failed: false }
                    } catch {
                        // `breakpoint()` drops a search that a newer one aborted. Other failures keep the client
                        // matches and show a notice instead of an error toast.
                        breakpoint()
                        if (controller.signal.aborted) {
                            return values.serverSearch
                        }
                        return { text, ids: [], failed: true }
                    }
                },
            },
        ],
    })),
    reducers(() => ({
        value: [
            EMPTY_VALUE,
            // Opening a workflow or the templates tab unmounts the list, and the way back carries no filters.
            buildUserScopedPersistenceConfig('workflows_list_v2_value__'),
            {
                setValue: (_, { value }) => value,
                clearFilters: () => EMPTY_VALUE,
            },
        ],
        requestedSearchText: [
            null as string | null,
            {
                searchWorkflows: (_, text) => text,
                setValue: (state, { value }) => (value.text.trim().length < MIN_SERVER_SEARCH_LENGTH ? null : state),
                clearFilters: () => null,
            },
        ],
        loadFailed: [
            false,
            {
                loadWorkflows: () => false,
                loadWorkflowsSuccess: () => false,
                loadWorkflowsFailure: () => true,
            },
        ],
        loadErrorDetail: [
            null as string | null,
            {
                loadWorkflows: () => null,
                loadWorkflowsSuccess: () => null,
                loadWorkflowsFailure: (_, { error, errorObject }) => loadErrorDetailOf(error, errorObject),
            },
        ],
        visibleColumns: [
            DEFAULT_COLUMNS as OptionalColumn[],
            { persist: true },
            {
                toggleColumn: (state, { column }) =>
                    state.includes(column)
                        ? state.filter((c) => c !== column)
                        : OPTIONAL_COLUMNS.filter((c) => c === column || state.includes(c)),
                resetColumns: () => DEFAULT_COLUMNS,
            },
        ],
        pendingRowActions: [
            {} as Record<string, WorkflowRowAction>,
            {
                setRowActionPending: (state, { id, action }) => {
                    const next = { ...state }
                    if (action) {
                        next[id] = action
                    } else {
                        delete next[id]
                    }
                    return next
                },
            },
        ],
        workflows: {
            patchWorkflow: (state, { id, patch }) => state && applyRowChange(state, { id, patch }),
            removeWorkflow: (state, { id }) => state && applyRowChange(state, { id, removed: true }),
        },
    })),
    selectors({
        hasHealthFilter: [
            (s) => [s.value],
            (value: FacetSearchValue): boolean => value.filters.some((filter) => filter.facet === 'health'),
        ],
        metricsLoaded: [(s) => [s.metrics], (metrics: WorkflowStatsRowApi[] | null): boolean => metrics !== null],
        isUnfilteredAutomationView: [
            (s) => [s.value],
            (value: FacetSearchValue): boolean =>
                !value.text &&
                value.filters.length === 1 &&
                value.filters[0].facet === 'kind' &&
                value.filters[0].value === 'automation' &&
                !value.filters[0].negated,
        ],
        templateTypeFilter: [
            (s) => [s.value],
            (value: FacetSearchValue): WorkflowTemplateTypeFilter => {
                const types = value.filters.filter((filter) => filter.facet === 'kind')
                const positive = [...new Set(types.filter((filter) => !filter.negated).map((filter) => filter.value))]
                const type = positive.length === 1 ? positive[0] : 'all'
                return (type === 'messaging' || type === 'automation') &&
                    !types.some((filter) => filter.negated && filter.value === type)
                    ? type
                    : 'all'
            },
        ],
        projectFilesEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.WORKFLOWS_PROJECT_FILES],
        ],
        rows: [
            (s) => [s.workflows, s.metrics],
            (workflows: HogFlowListSummaryApi[] | null, metrics: WorkflowStatsRowApi[] | null): WorkflowListRow[] =>
                workflows ? buildWorkflowListRows(workflows, metrics) : [],
        ],
        listLoaded: [(s) => [s.workflows], (workflows: HogFlowListSummaryApi[] | null): boolean => workflows !== null],
        facets: [
            (s) => [s.rows, s.itemsByRef, s.projectFilesEnabled, s.value, s.user],
            (
                rows: WorkflowListRow[],
                itemsByRef: Record<string, FileSystemEntry>,
                enabled: boolean,
                value: FacetSearchValue,
                user: UserType | null
            ): FacetDefinition<WorkflowListRow>[] =>
                buildWorkflowListFacets(
                    rows,
                    itemsByRef,
                    !!value.text.trim() || value.filters.some((filter) => filter.facet !== 'in' || filter.negated)
                )
                    .filter((facet) => enabled || facet.key !== 'in')
                    .map((facet) =>
                        facet.key === 'createdBy'
                            ? {
                                  ...facet,
                                  resolveValue: (value: string): string =>
                                      value.toLowerCase() === 'me'
                                          ? (user?.uuid ?? '__signed_out__')
                                          : (facet.resolveValue?.(value) ?? value),
                                  formatValue: (value: string): string =>
                                      value === 'me'
                                          ? user?.first_name || user?.email || 'Me'
                                          : (facet.formatValue?.(value) ?? value),
                              }
                            : facet
                    ),
        ],
        matchesText: [
            (s) => [s.serverSearch],
            (serverSearch: ServerSearchResult | null): MatchesText<WorkflowListRow> => {
                const serverIds = new Set(serverSearch?.ids ?? [])
                // The server also searches step names and email subjects and bodies, which the rows don't carry.
                return (row, text) =>
                    matchesWorkflowListText(row, text) || (serverSearch?.text === text.trim() && serverIds.has(row.id))
            },
        ],
        serverSearchStatus: [
            (s) => [s.value, s.serverSearch],
            (value: FacetSearchValue, serverSearch: ServerSearchResult | null): ServerSearchStatus => {
                const text = value.text.trim()
                if (text.length < MIN_SERVER_SEARCH_LENGTH) {
                    return 'off'
                }
                if (serverSearch?.text !== text) {
                    return 'pending'
                }
                return serverSearch.failed ? 'failed' : 'done'
            },
        ],
        filteredRows: [
            (s) => [s.rows, s.value, s.facets, s.matchesText],
            (
                rows: WorkflowListRow[],
                value: FacetSearchValue,
                facets: FacetDefinition<WorkflowListRow>[],
                matchesText: MatchesText<WorkflowListRow>
            ): WorkflowListRow[] => rows.filter(createFacetMatcher(value, facets, matchesText)),
        ],
        shownColumns: [
            (s) => [s.visibleColumns],
            // A saved choice can name a column this version doesn't have.
            (visibleColumns: OptionalColumn[]): OptionalColumn[] =>
                OPTIONAL_COLUMNS.filter((column) => visibleColumns.includes(column)),
        ],
    }),
    listeners(({ actions, values, cache }) => {
        /** Runs one network action per row at a time, so a second press can't send a second request. */
        const runRowAction = async (
            row: WorkflowListRow,
            action: WorkflowRowAction,
            run: () => Promise<void>
        ): Promise<void> => {
            if (values.pendingRowActions[row.id]) {
                return
            }
            actions.setRowActionPending(row.id, action)
            try {
                await run()
            } finally {
                actions.setRowActionPending(row.id, null)
            }
        }
        // Not `actionToUrl`: it hands kea-router a URL string, which parses `007` to 7 before writing it back.
        const writeUrl = (): void => {
            if (
                rawSearchParam('q') === serializeFacetQuery(values.value.filters) &&
                rawSearchParam('text') === values.value.text.trim()
            ) {
                return
            }
            router.actions.replace(
                router.values.location.pathname,
                withFacetParams(router.values.searchParams, values.value),
                router.values.hashParams
            )
        }
        return {
            refreshWorkflows: () => {
                actions.loadWorkflows()
                // A new workflow has a new id, so a server search from before it existed can't match it.
                const text = values.value.text.trim()
                if (text.length >= MIN_SERVER_SEARCH_LENGTH) {
                    actions.searchWorkflows(text)
                }
            },
            clearFilters: () => {
                cache.searchAbort?.abort()
                writeUrl()
            },
            setValue: ({ value }) => {
                writeUrl()
                const text = value.text.trim()
                if (text.length < MIN_SERVER_SEARCH_LENGTH) {
                    cache.searchAbort?.abort()
                } else if (values.requestedSearchText !== text) {
                    actions.searchWorkflows(text)
                }
            },
            patchWorkflow: ({ id, patch }) => {
                cache.rowChangesDuringLoad?.push({ id, patch })
            },
            removeWorkflow: ({ id }) => {
                cache.rowChangesDuringLoad?.push({ id, removed: true })
            },
            loadWorkflowsFailure: () => {
                if (values.listLoaded) {
                    lemonToast.error("Couldn't refresh workflows. Showing the list from before.")
                }
            },
            loadWorkflowsSuccess: () => {
                if (values.metrics === null && !values.metricsLoading) {
                    actions.loadMetrics()
                }
            },
            toggleWorkflowStatus: async ({ row }) => {
                await runRowAction(row, 'toggle', async () => {
                    const status = row.workflow.status === 'active' ? 'draft' : 'active'
                    const updated = await setWorkflowStatus(String(values.currentTeamId), row.workflow, status)
                    if (updated) {
                        actions.patchWorkflow(row.id, {
                            status: updated.status ?? status,
                            updated_at: updated.updated_at,
                        })
                    }
                })
            },
            duplicateWorkflow: async ({ row }) => {
                await runRowAction(row, 'duplicate', async () => {
                    const teamId = String(values.currentTeamId)
                    try {
                        // The summary row has no step graph, so the copy starts from the full workflow.
                        const full = await hogFlowsRetrieve(teamId, row.id)
                        await hogFlowsCreate(teamId, prepareWorkflowDuplicate(full))
                        lemonToast.success(`Workflow "${row.name}" duplicated`)
                        actions.refreshWorkflows()
                    } catch (error) {
                        lemonToast.error(`Failed to duplicate workflow: ${workflowActionErrorDetail(error)}`)
                    }
                })
            },
            archiveWorkflow: ({ row }) => {
                if (values.pendingRowActions[row.id]) {
                    return
                }
                confirmArchiveWorkflow(
                    String(values.currentTeamId),
                    row.workflow,
                    (updated) =>
                        actions.patchWorkflow(row.id, {
                            status: updated.status ?? 'archived',
                            updated_at: updated.updated_at,
                        }),
                    (pending) => actions.setRowActionPending(row.id, pending ? 'archive' : null)
                )
            },
            restoreWorkflow: async ({ row }) => {
                await runRowAction(row, 'restore', async () => {
                    const updated = await restoreWorkflowToDraft(String(values.currentTeamId), row.workflow)
                    if (updated) {
                        actions.patchWorkflow(row.id, {
                            status: updated.status ?? 'draft',
                            updated_at: updated.updated_at,
                        })
                    }
                })
            },
            deleteWorkflow: ({ row }) => {
                if (values.pendingRowActions[row.id]) {
                    return
                }
                confirmDeleteWorkflow(
                    String(values.currentTeamId),
                    row.workflow,
                    () => actions.removeWorkflow(row.id),
                    (pending) => actions.setRowActionPending(row.id, pending ? 'delete' : null)
                )
            },
        }
    }),
    urlToAction(({ actions, values, cache }) => {
        const syncFromUrl = (searchParams: Record<string, unknown>, hashParams: Record<string, unknown>): void => {
            const current: FacetSearchValue = {
                filters: parseFacetQuery(
                    rawSearchParam('q'),
                    QUERY_FACETS.filter((facet) => values.projectFilesEnabled || facet.key !== 'in')
                ),
                text: rawSearchParam('text'),
            }
            // Old filter links and the kept filters are read once, when the list opens. Later URLs are the list's own.
            if (!cache.legacyChecked) {
                cache.legacyChecked = true
                const kept = values.value
                if (
                    !('q' in searchParams || 'text' in searchParams) &&
                    !LEGACY_PARAMS.some((param) => param in searchParams) &&
                    (kept.filters.length > 0 || kept.text)
                ) {
                    router.actions.replace(
                        router.values.location.pathname,
                        withFacetParams(searchParams, kept),
                        hashParams
                    )
                    return
                }
                if (LEGACY_PARAMS.some((param) => param in searchParams)) {
                    const legacy = legacyParamsToValue(searchParams)
                    const next = { ...searchParams }
                    for (const param of LEGACY_PARAMS) {
                        delete next[param]
                    }
                    const merged = {
                        filters: [...current.filters, ...legacy.filters],
                        text: current.text || legacy.text,
                    }
                    router.actions.replace(router.values.location.pathname, withFacetParams(next, merged), hashParams)
                    return
                }
            }
            if (
                serializeFacetQuery(current.filters) !== serializeFacetQuery(values.value.filters) ||
                current.text !== values.value.text
            ) {
                actions.setValue(current)
            }
        }
        return {
            [urls.workflows()]: (_, searchParams, hashParams) => syncFromUrl(searchParams, hashParams),
            [urls.workflows('workflows')]: (_, searchParams, hashParams) => syncFromUrl(searchParams, hashParams),
        }
    }),
    afterMount(({ actions, values }) => {
        actions.loadWorkflows()
        // Kept text that equals the URL never reaches setValue, so its server search starts here.
        const text = values.value.text.trim()
        if (text.length >= MIN_SERVER_SEARCH_LENGTH && values.requestedSearchText !== text) {
            actions.searchWorkflows(text)
        }
    }),
    beforeUnmount(({ cache }) => {
        cache.searchAbort?.abort()
    }),
])
