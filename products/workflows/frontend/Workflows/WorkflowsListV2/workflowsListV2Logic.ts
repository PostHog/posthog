import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import {
    FacetDefinition,
    FacetFilter,
    FacetSearchValue,
    MatchesText,
    createFacetMatcher,
    parseFacetQuery,
    serializeFacetQuery,
} from 'lib/components/FacetSearchBar/facetQuery'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import {
    messagingTemplatesCreate,
    messagingTemplatesRetrieve,
    messagingTemplatesSummariesList,
} from 'products/messaging/frontend/generated/api'
import type { MessageTemplateListRowApi } from 'products/messaging/frontend/generated/api.schemas'
import { hogFlowsCreate, hogFlowsRetrieve, hogFlowsSummariesList } from 'products/workflows/frontend/generated/api'
import type { HogFlowListRowApi } from 'products/workflows/frontend/generated/api.schemas'

import { prepareWorkflowDuplicate } from '../workflowDuplication'
import {
    confirmArchiveWorkflow,
    confirmDeleteWorkflow,
    restoreWorkflowToDraft,
    setWorkflowStatus,
    workflowActionErrorDetail,
} from '../workflowRowActions'
import { buildWorkflowListFacets, matchesWorkflowListText } from './workflowListFacets'
import {
    LIST_TYPES,
    OPTIONAL_COLUMNS,
    OptionalColumn,
    STATUS_LABELS,
    TRIGGER_LABELS,
    TYPE_LABELS,
} from './workflowListLabels'
import { EmailTemplateRow, WorkflowListRow, WorkflowRow, buildWorkflowListRows } from './workflowListRows'

const WORKFLOWS_PAGE_TYPES = LIST_TYPES.join(',')
const PAGE_LIMIT = 1000
// 20,000 rows per endpoint; a `next` link that never ends shows the load error instead of looping.
const MAX_PAGES = 20
const MIN_SERVER_SEARCH_LENGTH = 3
const SERVER_SEARCH_DEBOUNCE_MS = 300

export interface WorkflowsListData {
    workflows: HogFlowListRowApi[]
    templates: MessageTemplateListRowApi[]
}

export interface ServerSearchResult {
    text: string
    ids: string[]
}

interface Page<T> {
    next?: string | null
    results: T[]
}

const EMPTY_VALUE: FacetSearchValue = { filters: [], text: '' }
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
const LEGACY_PARAMS = ['status', 'type', 'trigger_type', 'created_by', 'search', 'page'] as const
const LEGACY_VALUES: Record<string, (value: string) => boolean> = {
    status: (value) => value in STATUS_LABELS,
    type: (value) => value in TYPE_LABELS,
    trigger: (value) => value in TRIGGER_LABELS,
    'created-by': (value) => UUID_PATTERN.test(value),
}

// Parsing only needs facet keys and aliases, which don't depend on the loaded rows.
const QUERY_FACETS = buildWorkflowListFacets([])

/** Follows `next` to the end. Rows are keyed by id, because a row created mid-load shifts later offsets. */
async function loadAllPages<T extends { id: string }>(
    fetchPage: (offset: number | undefined) => Promise<Page<T>>
): Promise<T[]> {
    const byId = new Map<string, T>()
    let offset: number | undefined = undefined
    for (let pages = 0; pages < MAX_PAGES; pages++) {
        const page: Page<T> = await fetchPage(offset)
        for (const row of page.results) {
            byId.set(row.id, byId.get(row.id) ?? row)
        }
        const nextOffset = page.next ? new URL(page.next, window.location.origin).searchParams.get('offset') : null
        if (!nextOffset || !page.results.length) {
            return [...byId.values()]
        }
        offset = Number(nextOffset)
    }
    throw new Error(`Stopped loading after ${MAX_PAGES} pages`)
}

/** Reads a param as written. kea-router turns number-like values such as `007` into numbers. */
function rawSearchParam(name: string): string {
    return new URLSearchParams(router.values.location.search).get(name) ?? ''
}

/** Writes `q` and `text` into a copy of the search params, dropping each one when it is empty. */
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
    const pairs: [string, string][] = [
        ['status', 'status'],
        ['type', 'type'],
        ['trigger_type', 'trigger'],
        ['created_by', 'created-by'],
    ]
    for (const [param, facet] of pairs) {
        const raw = searchParams[param]
        const value = raw === undefined || raw === null ? '' : String(raw)
        if (value && LEGACY_VALUES[facet](value)) {
            filters.push({ facet, value, negated: false })
        }
    }
    return { filters, text: rawSearchParam('search') }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowsListV2LogicValues {
    currentTeamId: number | null // teamLogic
    facets: FacetDefinition<WorkflowListRow>[]
    filteredRows: WorkflowListRow[]
    listData: WorkflowsListData | null
    listDataLoading: boolean
    listLoaded: boolean
    loadFailed: boolean
    matchesText: MatchesText<WorkflowListRow>
    requestedSearchText: string | null
    rows: WorkflowListRow[]
    serverSearch: ServerSearchResult | null
    serverSearchLoading: boolean
    shownColumns: OptionalColumn[]
    value: FacetSearchValue
    visibleColumns: OptionalColumn[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowsListV2LogicActions {
    archiveWorkflow: (row: WorkflowRow) => {
        row: WorkflowRow
    }
    clearFilters: () => {
        value: true
    }
    deleteTemplate: (row: EmailTemplateRow) => {
        row: EmailTemplateRow
    }
    deleteWorkflow: (row: WorkflowRow) => {
        row: WorkflowRow
    }
    duplicateTemplate: (row: EmailTemplateRow) => {
        row: EmailTemplateRow
    }
    duplicateWorkflow: (row: WorkflowRow) => {
        row: WorkflowRow
    }
    loadList: () => {
        value: true
    }
    loadListFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadListSuccess: (
        listData: {
            templates: MessageTemplateListRowApi[]
            workflows: HogFlowListRowApi[]
        },
        payload?: {
            value: true
        }
    ) => {
        listData: {
            templates: MessageTemplateListRowApi[]
            workflows: HogFlowListRowApi[]
        }
        payload?: {
            value: true
        }
    }
    patchWorkflow: (
        id: string,
        patch: Partial<HogFlowListRowApi>
    ) => {
        id: string
        patch: Partial<HogFlowListRowApi>
    }
    removeRow: (id: string) => {
        id: string
    }
    resetColumns: () => {
        value: true
    }
    restoreWorkflow: (row: WorkflowRow) => {
        row: WorkflowRow
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
        serverSearch: {
            ids: string[]
            text: string
        },
        payload?: string
    ) => {
        serverSearch: {
            ids: string[]
            text: string
        }
        payload?: string
    }
    setValue: (value: FacetSearchValue) => {
        value: FacetSearchValue
    }
    toggleColumn: (column: OptionalColumn) => {
        column: 'created_by' | 'health' | 'last_7_days' | 'owner' | 'trigger' | 'type'
    }
    toggleWorkflowStatus: (row: WorkflowRow) => {
        row: WorkflowRow
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface workflowsListV2LogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        rows: (listData: WorkflowsListData | null) => WorkflowListRow[]
        listLoaded: (listData: WorkflowsListData | null) => boolean
        facets: (rows: WorkflowListRow[]) => FacetDefinition<WorkflowListRow>[]
        matchesText: (serverSearch: ServerSearchResult | null) => MatchesText<WorkflowListRow>
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
    // `hog_flows` and `messaging_templates` are looked up by team, and a child environment's team id
    // differs from its project id.
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        loadList: true,
        setValue: (value: FacetSearchValue) => ({ value }),
        clearFilters: true,
        toggleColumn: (column: OptionalColumn) => ({ column }),
        resetColumns: true,
        patchWorkflow: (id: string, patch: Partial<HogFlowListRowApi>) => ({ id, patch }),
        removeRow: (id: string) => ({ id }),
        toggleWorkflowStatus: (row: WorkflowRow) => ({ row }),
        duplicateWorkflow: (row: WorkflowRow) => ({ row }),
        archiveWorkflow: (row: WorkflowRow) => ({ row }),
        restoreWorkflow: (row: WorkflowRow) => ({ row }),
        deleteWorkflow: (row: WorkflowRow) => ({ row }),
        duplicateTemplate: (row: EmailTemplateRow) => ({ row }),
        deleteTemplate: (row: EmailTemplateRow) => ({ row }),
    }),
    loaders(({ values, cache }) => ({
        listData: [
            null as WorkflowsListData | null,
            {
                loadList: async (_, breakpoint) => {
                    const teamId = String(values.currentTeamId)
                    const [workflows, templates] = await Promise.all([
                        loadAllPages((offset) =>
                            hogFlowsSummariesList(teamId, { type: WORKFLOWS_PAGE_TYPES, limit: PAGE_LIMIT, offset })
                        ),
                        loadAllPages((offset) =>
                            messagingTemplatesSummariesList(teamId, { limit: PAGE_LIMIT, offset })
                        ),
                    ])
                    breakpoint()
                    return { workflows, templates }
                },
            },
        ],
        serverSearch: [
            null as ServerSearchResult | null,
            {
                searchWorkflows: async (text: string, breakpoint) => {
                    await breakpoint(SERVER_SEARCH_DEBOUNCE_MS)
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
                        return { text, ids: workflows.map((workflow) => workflow.id) }
                    } catch (error) {
                        // A newer search aborted this one; drop it quietly.
                        breakpoint()
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        value: [
            EMPTY_VALUE,
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
                loadList: () => false,
                loadListSuccess: () => false,
                loadListFailure: () => true,
            },
        ],
        visibleColumns: [
            [] as OptionalColumn[],
            { persist: true },
            {
                toggleColumn: (state, { column }) =>
                    state.includes(column)
                        ? state.filter((c) => c !== column)
                        : OPTIONAL_COLUMNS.filter((c) => c === column || state.includes(c)),
                resetColumns: () => [],
            },
        ],
        listData: {
            patchWorkflow: (state, { id, patch }) =>
                state && {
                    ...state,
                    workflows: state.workflows.map((workflow) =>
                        workflow.id === id ? { ...workflow, ...patch } : workflow
                    ),
                },
            removeRow: (state, { id }) =>
                state && {
                    workflows: state.workflows.filter((workflow) => workflow.id !== id),
                    templates: state.templates.filter((template) => template.id !== id),
                },
        },
    }),
    selectors({
        rows: [
            (s) => [s.listData],
            (listData: WorkflowsListData | null): WorkflowListRow[] =>
                listData ? buildWorkflowListRows(listData.workflows, listData.templates) : [],
        ],
        listLoaded: [(s) => [s.listData], (listData: WorkflowsListData | null): boolean => listData !== null],
        facets: [
            (s) => [s.rows],
            (rows: WorkflowListRow[]): FacetDefinition<WorkflowListRow>[] => buildWorkflowListFacets(rows),
        ],
        matchesText: [
            (s) => [s.serverSearch],
            (serverSearch: ServerSearchResult | null): MatchesText<WorkflowListRow> => {
                const serverIds = new Set(serverSearch?.ids ?? [])
                // The server also searches email bodies and preheaders, which the slim rows don't carry.
                return (row, text) =>
                    matchesWorkflowListText(row, text) ||
                    (row.kind === 'workflow' && serverSearch?.text === text.trim() && serverIds.has(row.id))
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
    listeners(({ actions, values }) => {
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
            clearFilters: writeUrl,
            setValue: ({ value }) => {
                writeUrl()
                const text = value.text.trim()
                if (text.length >= MIN_SERVER_SEARCH_LENGTH && values.requestedSearchText !== text) {
                    actions.searchWorkflows(text)
                }
            },
            toggleWorkflowStatus: async ({ row }) => {
                const status = row.workflow.status === 'active' ? 'draft' : 'active'
                if (await setWorkflowStatus(String(values.currentTeamId), row.workflow, status)) {
                    actions.patchWorkflow(row.id, { status })
                }
            },
            duplicateWorkflow: async ({ row }) => {
                const teamId = String(values.currentTeamId)
                try {
                    // The slim row has no step graph, so the copy starts from the full workflow.
                    const full = await hogFlowsRetrieve(teamId, row.id)
                    await hogFlowsCreate(teamId, prepareWorkflowDuplicate(full))
                    lemonToast.success(`Workflow "${row.name}" duplicated`)
                    actions.loadList()
                } catch (error) {
                    lemonToast.error(`Failed to duplicate workflow: ${workflowActionErrorDetail(error)}`)
                }
            },
            archiveWorkflow: ({ row }) => {
                confirmArchiveWorkflow(String(values.currentTeamId), row.workflow, () =>
                    actions.patchWorkflow(row.id, { status: 'archived' })
                )
            },
            restoreWorkflow: async ({ row }) => {
                if (await restoreWorkflowToDraft(String(values.currentTeamId), row.workflow)) {
                    actions.patchWorkflow(row.id, { status: 'draft' })
                }
            },
            deleteWorkflow: ({ row }) => {
                confirmDeleteWorkflow(String(values.currentTeamId), row.workflow, () => actions.removeRow(row.id))
            },
            duplicateTemplate: async ({ row }) => {
                const teamId = String(values.currentTeamId)
                try {
                    // The slim row has no content, so the copy starts from the full template.
                    const full = await messagingTemplatesRetrieve(teamId, row.id)
                    await messagingTemplatesCreate(teamId, {
                        name: `${full.name} (copy)`,
                        description: full.description,
                        content: full.content,
                    })
                    lemonToast.success('Template duplicated successfully')
                    actions.loadList()
                } catch {
                    lemonToast.error('Failed to duplicate template')
                }
            },
            deleteTemplate: async ({ row }) => {
                await deleteWithUndo({
                    endpoint: `projects/${values.currentTeamId}/messaging_templates`,
                    object: { id: row.id, name: row.name },
                    // Runs only after the server accepted the change.
                    callback: (undo) => (undo ? actions.loadList() : actions.removeRow(row.id)),
                })
            },
        }
    }),
    urlToAction(({ actions, values, cache }) => ({
        [urls.workflows()]: (_, searchParams, hashParams) => {
            const current: FacetSearchValue = {
                filters: parseFacetQuery(rawSearchParam('q'), QUERY_FACETS),
                text: rawSearchParam('text'),
            }
            // Old filter links are read once, when the list opens. Later URLs are the list's own.
            if (!cache.legacyChecked) {
                cache.legacyChecked = true
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
                    router.actions.replace(urls.workflows(), withFacetParams(next, merged), hashParams)
                    return
                }
            }
            if (
                serializeFacetQuery(current.filters) !== serializeFacetQuery(values.value.filters) ||
                current.text !== values.value.text
            ) {
                actions.setValue(current)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadList()
    }),
])
