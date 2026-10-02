import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import { availableInboxSortOptions, INBOX_PRIORITY_OPTIONS, INBOX_SOURCE_OPTIONS } from '../filterOptions'
import { captureInboxQueryChanged, InboxQueryChange } from '../inboxAnalytics'
import { parseTeammateInboxScope } from '../inboxMembership'
import {
    INBOX_LEGACY_TAB_KEYS,
    INBOX_REPORT_SECTION_KEYS,
    INBOX_SCOPE_FOR_YOU,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    INBOX_TAB_KEYS,
    InboxReportSectionKey,
    InboxScope,
    SignalReportPriority,
} from '../types'
import { isInboxRedesignEnabled } from '../utils/inboxRedesign'

/** A teammate who can be scoped to / suggested as a reviewer. Matches the `available_reviewers` API row. */
export interface InboxReviewerOption {
    user_uuid: string
    name: string
    email: string
}

/** The sort fields the server can order by through `ordering`. */
export type InboxSortField = 'priority' | 'created_at' | 'updated_at'
/** `relevance` is the server's personal ranking, sent as `sort=relevance` and only valid with `scope=for_me`. */
export type InboxListSortField = InboxSortField | 'relevance'
export type InboxSortDirection = 'asc' | 'desc'

export interface InboxSort {
    field: InboxListSortField
    direction: InboxSortDirection
}

const DEFAULT_SORT_FIELD: InboxSortField = 'priority'
const DEFAULT_SORT_DIRECTION: InboxSortDirection = 'asc'
export const DEFAULT_INBOX_SORT: { field: InboxSortField; direction: InboxSortDirection } = {
    field: DEFAULT_SORT_FIELD,
    direction: DEFAULT_SORT_DIRECTION,
}

/**
 * The states selected by default: the two that hold open work. The closed states (Resolved,
 * Dismissed) stay one checkbox away so the fresh inbox leads with what needs a person.
 */
export const DEFAULT_STATE_FILTER: InboxReportSectionKey[] = ['monitoring', 'needs-decision']

/**
 * URL value for an explicitly empty selection (every state). An absent `state` param means the
 * default selection, so the empty selection needs its own encoding; without it, the URL rewrite
 * after unchecking the last state would immediately hydrate the default back.
 */
const STATE_PARAM_ALL = 'all'

/** Whether a state selection is exactly the default, in any order. */
export function isDefaultStateFilter(stateFilter: InboxReportSectionKey[]): boolean {
    return sameSet(stateFilter, DEFAULT_STATE_FILTER)
}

// Query-param keys that mirror the filter state so a view can be shared via URL.
const FILTER_URL_KEYS = ['scope', 'source', 'scout', 'priority', 'state', 'sort', 'search'] as const

const VALID_SOURCE_VALUES = new Set(INBOX_SOURCE_OPTIONS.map((o) => o.value))
const VALID_PRIORITIES = new Set<string>(INBOX_PRIORITY_OPTIONS)
const VALID_STATE_VALUES = new Set<string>(INBOX_REPORT_SECTION_KEYS)
// Only the field/direction combinations the Sort control actually offers — validating the field and
// direction independently would accept keys like `priority:desc` that have no matching UI option.
const VALID_SORT_KEYS = new Set(availableInboxSortOptions(true).map((o) => `${o.field}:${o.direction}`))

export interface InboxFilterState {
    scope: InboxScope
    sourceProductFilter: string[]
    scoutFilter: string[]
    priorityFilter: SignalReportPriority[]
    stateFilter: InboxReportSectionKey[]
    sortField: InboxListSortField
    sortDirection: InboxSortDirection
    /** Whether the stored sort is an explicit choice. Only an explicit choice overrides the relevance default. */
    hasUserChosenSort: boolean
    searchQuery: string
}

function parseScopeParam(raw: unknown): InboxScope {
    if (typeof raw === 'string') {
        if (raw === 'entire-project') {
            return raw
        }
        // Validate the teammate id so a malformed shared link falls back to the default scope
        // instead of forwarding junk to the report-list API as a reviewer UUID.
        if (raw.startsWith('teammate:') && isUUIDLike(raw.slice('teammate:'.length))) {
            return raw as InboxScope
        }
    }
    return INBOX_SCOPE_FOR_YOU
}

function parseListParam(raw: unknown, valid: Set<string>): string[] {
    if (typeof raw !== 'string' || raw.length === 0) {
        return []
    }
    return raw.split(',').filter((v) => valid.has(v))
}

/**
 * Decode the `state` param: the sentinel means every state, an explicit list is validated, and
 * anything else (absent, or nothing but unknown values) falls back to the default selection.
 */
function parseStateParam(raw: unknown): InboxReportSectionKey[] {
    if (raw === STATE_PARAM_ALL) {
        return []
    }
    const parsed = parseListParam(raw, VALID_STATE_VALUES) as InboxReportSectionKey[]
    return parsed.length > 0 ? parsed : DEFAULT_STATE_FILTER
}

// Scout skill names are team-specific and dynamic, so there is no static valid set to check a
// shared link against — accept any non-empty comma-separated slugs; an unknown scout simply
// matches no reports server-side.
function parseScoutParam(raw: unknown): string[] {
    if (typeof raw !== 'string' || raw.length === 0) {
        return []
    }
    return raw
        .split(',')
        .map((v) => v.trim())
        .filter((v) => v.length > 0)
}

/** Decode the filter query params into filter state, ignoring unknown/invalid values and falling back to defaults. */
export function parseFilterSearchParams(searchParams: Record<string, any>): InboxFilterState {
    let sortField: InboxListSortField = DEFAULT_SORT_FIELD
    let sortDirection = DEFAULT_SORT_DIRECTION
    let hasUserChosenSort = false
    if (typeof searchParams.sort === 'string' && VALID_SORT_KEYS.has(searchParams.sort)) {
        const [field, direction] = searchParams.sort.split(':')
        sortField = field as InboxListSortField
        sortDirection = direction as InboxSortDirection
        hasUserChosenSort = true
    }
    return {
        scope: parseScopeParam(searchParams.scope),
        sourceProductFilter: parseListParam(searchParams.source, VALID_SOURCE_VALUES),
        scoutFilter: parseScoutParam(searchParams.scout),
        priorityFilter: parseListParam(searchParams.priority, VALID_PRIORITIES) as SignalReportPriority[],
        stateFilter: parseStateParam(searchParams.state),
        sortField,
        sortDirection,
        hasUserChosenSort,
        searchQuery: typeof searchParams.search === 'string' ? searchParams.search : '',
    }
}

/**
 * The inbox page tab the filters apply to, for the `tab` analytics property: the tab segment from
 * the URL (`reports`, `scouts`, or `settings` under the redesign, or a legacy tab key), or null off
 * a tab route (the scout panels, or a bare `/inbox`). The redesigned Reports tab is one flat list
 * with no sub-view, so it reports `reports` and stays consistent with the `tab` that
 * `captureInboxViewed` sends for the same visit. Read from the router rather than connected from
 * `inboxSceneLogic`, which already connects this logic, because the reverse edge would be a cycle.
 */
function currentInboxTab(redesign: boolean): string | null {
    const segments = router.values.location.pathname.split('/').filter(Boolean)
    const inboxIndex = segments.indexOf('inbox')
    const candidate = inboxIndex === -1 ? undefined : segments[inboxIndex + 1]
    const tabKeys = (redesign ? INBOX_TAB_KEYS : INBOX_LEGACY_TAB_KEYS) as string[]
    if (!candidate || !tabKeys.includes(candidate)) {
        return null
    }
    return candidate
}

function sameSet(a: string[], b: string[]): boolean {
    return a.length === b.length && [...a].sort().join(',') === [...b].sort().join(',')
}

/** Build the query params that mirror the current (non-default) filter state. Defaults are omitted so a shared URL stays clean. */
export function filterSearchParams(values: InboxFilterState): Record<string, string> {
    const params: Record<string, string> = {}
    if (values.scope !== INBOX_SCOPE_FOR_YOU) {
        params.scope = values.scope
    }
    if (values.sourceProductFilter.length > 0) {
        params.source = values.sourceProductFilter.join(',')
    }
    if (values.scoutFilter.length > 0) {
        params.scout = values.scoutFilter.join(',')
    }
    if (values.priorityFilter.length > 0) {
        params.priority = values.priorityFilter.join(',')
    }
    if (values.stateFilter.length === 0) {
        params.state = STATE_PARAM_ALL
    } else if (!isDefaultStateFilter(values.stateFilter)) {
        params.state = values.stateFilter.join(',')
    }
    // An explicit "Priority first" still goes in the URL, so a recipient whose default is relevance
    // sees the order the sender picked.
    if (
        values.hasUserChosenSort ||
        values.sortField !== DEFAULT_SORT_FIELD ||
        values.sortDirection !== DEFAULT_SORT_DIRECTION
    ) {
        params.sort = `${values.sortField}:${values.sortDirection}`
    }
    if (values.searchQuery.trim().length > 0) {
        params.search = values.searchQuery
    }
    return params
}

/**
 * Build the state-mirroring inbox URL for the current pathname: keep any non-filter query params,
 * drop stale filter keys, then write the current non-default filter state back on. `replace: true`
 * keeps filter toggles out of the browser history.
 */
function currentUrlWithFilters(values: InboxFilterState): [string, Record<string, any>, any, { replace: boolean }] {
    const searchParams = { ...router.values.searchParams }
    for (const key of FILTER_URL_KEYS) {
        delete searchParams[key]
    }
    Object.assign(searchParams, filterSearchParams(values))
    return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
}

/**
 * Build the `ordering` query param. The list is a flat list (no status section
 * headers), so the toolbar-selected field must lead — otherwise an explicit sort
 * like "Newest first" only reorders reports *within* each status bucket and the
 * genuinely newest reports never reach the top:
 * 1. Toolbar-selected field (priority, updated_at, created_at) with direction
 * 2. Status rank (semantic server-side rank) as a secondary key, so reports tied
 *    on the selected field surface in pipeline-status order
 * 3. `-updated_at` as a final recency tiebreak (skipped when the selected field
 *    is already `updated_at`).
 *
 * Reviewer scope is NOT an ordering tiebreak. A `-is_suggested_reviewer` sort
 * floats the current user's own reports to the top of the single loaded page,
 * which starves the "Entire project" scope of genuinely project-wide reports
 * once the list exceeds one page. Scope is applied separately (client-side here),
 * matching desktop fix #2699.
 */
export function buildSignalReportListOrdering(field: InboxSortField, direction: InboxSortDirection): string {
    const fieldKey = direction === 'desc' ? `-${field}` : field
    return field === 'updated_at' ? `${fieldKey},status` : `${fieldKey},status,-updated_at`
}

/**
 * The sort the list uses. Relevance is available only on the For-you scope with the personal inbox
 * on, because the server rejects it on any other scope. There it is the default unless the user
 * picked another sort. A stored sort other than the default also counts as a pick, because a
 * persisted sort can be older than `hasUserChosenSort`. On any other scope a stored relevance sort
 * falls back to the default order.
 */
export function resolveInboxSort(input: {
    sortField: InboxListSortField
    sortDirection: InboxSortDirection
    hasUserChosenSort: boolean
    relevanceAvailable: boolean
}): InboxSort {
    if (!input.relevanceAvailable) {
        return input.sortField === 'relevance'
            ? DEFAULT_INBOX_SORT
            : { field: input.sortField, direction: input.sortDirection }
    }
    const storedIsDefault = input.sortField === DEFAULT_SORT_FIELD && input.sortDirection === DEFAULT_SORT_DIRECTION
    if (!input.hasUserChosenSort && storedIsDefault) {
        return { field: 'relevance', direction: 'asc' }
    }
    return { field: input.sortField, direction: input.sortDirection }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxFiltersLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    user: UserType | null // userLogic
    activeSort: InboxSort
    availableReviewers: InboxReviewerOption[]
    availableReviewersLoading: boolean
    hasActiveFilters: boolean
    hasUserChosenScope: boolean
    hasUserChosenSort: boolean
    isPersonalInboxEnabled: boolean
    isRedesign: boolean
    isRelevanceSortAvailable: boolean
    knownTeammate: {
        label: string
        uuid: string
    } | null
    priorityFilter: SignalReportPriority[]
    scope: InboxScope
    scoutFilter: string[]
    searchQuery: string
    sortDirection: InboxSortDirection
    sortField: InboxListSortField
    sourceProductFilter: string[]
    stateFilter: ('dismissed' | 'monitoring' | 'needs-decision' | 'not-actionable' | 'resolved')[]
    visibleStateFilter: InboxReportSectionKey[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxFiltersLogicActions {
    applyDefaultScope: (scope: InboxScope) => {
        scope: InboxScope
    }
    clearFilters: () => {
        value: true
    }
    clearScoutFilter: () => {
        value: true
    }
    loadAvailableReviewers: ({ query }?: { query?: string }) => {
        query?: string
    }
    loadAvailableReviewersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAvailableReviewersSuccess: (
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[],
        payload?: {
            query?: string
        }
    ) => {
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[]
        payload?: {
            query?: string
        }
    }
    searchAvailableReviewers: (query: string) => {
        query: string
    }
    setFilters: (filters: InboxFilterState) => {
        filters: InboxFilterState
    }
    setKnownTeammate: (
        uuid: string,
        label: string
    ) => {
        label: string
        uuid: string
    }
    setPriorityFilter: (priorities: SignalReportPriority[]) => {
        priorities: SignalReportPriority[]
    }
    setScope: (scope: InboxScope) => {
        scope: InboxScope
    }
    setSearchQuery: (searchQuery: string) => {
        searchQuery: string
    }
    setSort: (
        field: InboxListSortField,
        direction: InboxSortDirection
    ) => {
        direction: InboxSortDirection
        field: InboxListSortField
    }
    togglePriority: (priority: SignalReportPriority) => {
        priority: SignalReportPriority
    }
    toggleScout: (scout: string) => {
        scout: string
    }
    toggleSourceProduct: (source: string) => {
        source: string
    }
    toggleState: (state: InboxReportSectionKey) => {
        state: 'dismissed' | 'monitoring' | 'needs-decision' | 'not-actionable' | 'resolved'
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxFiltersLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        hasActiveFilters: (
            searchQuery: string,
            sourceProductFilter: string[],
            scoutFilter: string[],
            priorityFilter: SignalReportPriority[]
        ) => boolean
        isRedesign: (featureFlags: FeatureFlagsSet) => boolean
        isPersonalInboxEnabled: (featureFlags: FeatureFlagsSet) => boolean
        isRelevanceSortAvailable: (isPersonalInboxEnabled: boolean, scope: InboxScope) => boolean
        activeSort: (
            sortField: InboxListSortField,
            sortDirection: InboxSortDirection,
            hasUserChosenSort: boolean,
            isRelevanceSortAvailable: boolean
        ) => InboxSort
        visibleStateFilter: (
            stateFilter: ('dismissed' | 'monitoring' | 'needs-decision' | 'not-actionable' | 'resolved')[],
            user: UserType | null
        ) => InboxReportSectionKey[]
    }
}

export type inboxFiltersLogicType = MakeLogicType<
    inboxFiltersLogicValues,
    inboxFiltersLogicActions,
    Record<string, any>,
    inboxFiltersLogicMeta
>

/**
 * Persisted inbox filter state. Mirrors desktop's zustand stores:
 * - `inboxReviewerScopeStore` → `scope` (persisted, default "for-you")
 * - `inboxSignalsFilterStore` v2 → `sortField`/`sortDirection` (default priority/asc),
 *   `sourceProductFilter`, `priorityFilter` (all persisted). `searchQuery` is NOT
 *   persisted on desktop, so it isn't here either.
 *
 * Filter state (scope, source, priority, sort) is also mirrored to the URL query
 * string so a specific view can be shared via a link. The URL is authoritative on
 * load whenever any filter param is present; a bare `/inbox` falls back to the
 * persisted state (and is then reflected back into the URL so it stays shareable).
 *
 * The central `inboxSceneLogic` connects these values, maps them to list-API
 * params (`source_product`, `priority`, `ordering`), and reloads on change.
 */
export const inboxFiltersLogic = kea<inboxFiltersLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxFiltersLogic']),

    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], userLogic, ['user']],
    })),

    actions({
        setScope: (scope: InboxScope) => ({ scope }),
        setKnownTeammate: (uuid: string, label: string) => ({ uuid, label }),
        // Auto-select a default scope (e.g. Entire project when the user has no assigned reports)
        // without marking it as an explicit user choice, so a later real choice still wins and persists.
        applyDefaultScope: (scope: InboxScope) => ({ scope }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSort: (field: InboxListSortField, direction: InboxSortDirection) => ({ field, direction }),
        toggleSourceProduct: (source: string) => ({ source }),
        toggleScout: (scout: string) => ({ scout }),
        clearScoutFilter: true,
        togglePriority: (priority: SignalReportPriority) => ({ priority }),
        // The report states (Needs decision, Review and merge, …) shown in the flat Reports list.
        // Multi-select: the open-work states are selected by default (DEFAULT_STATE_FILTER), and an
        // empty selection means every state the user can see.
        toggleState: (state: InboxReportSectionKey) => ({ state }),
        // Replace the whole selection. The priority control is a single select, but the state
        // stays a list so a shared link carrying several priorities still filters by all of them.
        setPriorityFilter: (priorities: SignalReportPriority[]) => ({ priorities }),
        // Atomically apply a full filter set. Used when hydrating from a shared URL so the whole view
        // is restored in one action — one list refresh, no fan-out race between partial states.
        setFilters: (filters: InboxFilterState) => ({ filters }),
        clearFilters: true,
        // Debounced server-side org-member search for the scope (teammate) picker.
        searchAvailableReviewers: (query: string) => ({ query }),
    }),

    loaders({
        // Shared, project-wide reviewer roster used by the scope picker. Filtered server-side via
        // `query` (backend ranks + caps at 100) so the picker isn't limited to the alphabetical first page.
        availableReviewers: [
            [] as InboxReviewerOption[],
            {
                loadAvailableReviewers: async ({ query }: { query?: string } = {}, breakpoint) => {
                    // The api wrapper already returns the typed `{ user_uuid, name, email }[]` array.
                    const reviewers = await api.signalReports.availableReviewers(query)
                    // Discard this result if a newer search superseded it while the request was in
                    // flight, so a slower earlier response cannot overwrite the newer rows.
                    breakpoint()
                    return reviewers
                },
            },
        ],
    }),

    listeners(({ actions, values }) => {
        // Listeners run after reducers, so `values` is already the query the user landed on.
        const captureQueryChange = (change: InboxQueryChange): void =>
            captureInboxQueryChanged({
                change,
                tab: currentInboxTab(values.isRedesign),
                scope: values.scope,
                sortField: values.activeSort.field,
                sortDirection: values.activeSort.direction,
                sourceProductFilter: values.sourceProductFilter,
                scoutFilter: values.scoutFilter,
                priorityFilter: values.priorityFilter,
                stateFilter: values.stateFilter,
                searchQuery: values.searchQuery,
                hasActiveFilters: values.hasActiveFilters,
            })

        const rememberSelectedTeammate = (): void => {
            const uuid = parseTeammateInboxScope(values.scope)
            const reviewer = values.availableReviewers.find((reviewer) => reviewer.user_uuid === uuid)
            if (uuid && reviewer) {
                actions.setKnownTeammate(uuid, reviewer.name || reviewer.email)
            }
        }

        return {
            loadAvailableReviewersSuccess: rememberSelectedTeammate,
            searchAvailableReviewers: async ({ query }, breakpoint) => {
                await breakpoint(300)
                actions.loadAvailableReviewers({ query: query.trim() || undefined })
            },
            // `applyDefaultScope` is deliberately absent — it's the empty-inbox auto-default, not a
            // user choice, and counting it as engagement is exactly the inflation we're trying to avoid.
            setScope: () => {
                rememberSelectedTeammate()
                captureQueryChange('scope')
            },
            setSort: () => captureQueryChange('sort'),
            toggleSourceProduct: () => captureQueryChange('source_product'),
            toggleScout: () => captureQueryChange('scout'),
            clearScoutFilter: () => captureQueryChange('scout'),
            togglePriority: () => captureQueryChange('priority'),
            setPriorityFilter: () => captureQueryChange('priority'),
            toggleState: () => captureQueryChange('state'),
            clearFilters: () => captureQueryChange('clear'),
            setFilters: () => {
                rememberSelectedTeammate()
                captureQueryChange('url')
            },
            // The search box fires per keystroke; settle first so a typed phrase is one event.
            setSearchQuery: async (_, breakpoint) => {
                await breakpoint(600)
                captureQueryChange('search')
            },
        }
    }),

    reducers({
        // Keep the selected label when a search removes its row from the returned roster.
        knownTeammate: [
            null as { uuid: string; label: string } | null,
            { setKnownTeammate: (_, { uuid, label }) => ({ uuid, label }) },
        ],
        scope: [
            INBOX_SCOPE_FOR_YOU as InboxScope,
            { persist: true },
            {
                setScope: (_, { scope }) => scope,
                applyDefaultScope: (_, { scope }) => scope,
                setFilters: (_, { filters }) => filters.scope,
            },
        ],
        // Whether the user has explicitly picked a scope. Once true, the empty-inbox auto-default
        // no longer fires, so a deliberate choice of "For you" is respected even with zero reports.
        // A shared link is an explicit choice too, so hydrating from the URL sets it.
        hasUserChosenScope: [
            false,
            { persist: true },
            {
                setScope: () => true,
                setFilters: () => true,
            },
        ],
        // Not persisted – matches desktop (searchQuery is excluded from `partialize`). It is mirrored to
        // the URL though, so a shared link reproduces the search too and hydration can reset it.
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
                setFilters: (_, { filters }) => filters.searchQuery,
                clearFilters: () => '',
            },
        ],
        sortField: [
            DEFAULT_SORT_FIELD as InboxListSortField,
            { persist: true },
            {
                setSort: (_, { field }) => field,
                setFilters: (_, { filters }) => filters.sortField,
            },
        ],
        sortDirection: [
            DEFAULT_SORT_DIRECTION as InboxSortDirection,
            { persist: true },
            {
                setSort: (_, { direction }) => direction,
                setFilters: (_, { filters }) => filters.sortDirection,
            },
        ],
        // Whether the user has explicitly picked a sort. Until then the For-you scope of the personal
        // inbox uses relevance (see `resolveInboxSort`).
        hasUserChosenSort: [
            false,
            { persist: true },
            {
                setSort: () => true,
                setFilters: (_, { filters }) => filters.hasUserChosenSort,
            },
        ],
        sourceProductFilter: [
            [] as string[],
            { persist: true },
            {
                toggleSourceProduct: (state, { source }) =>
                    state.includes(source) ? state.filter((s) => s !== source) : [...state, source],
                setFilters: (_, { filters }) => filters.sourceProductFilter,
                clearFilters: () => [],
            },
        ],
        // Raw scout skill_name slugs (e.g. "signals-scout-error-tracking") — a sub-filter of the
        // Scout source, narrowing to reports authored by specific scouts.
        scoutFilter: [
            [] as string[],
            { persist: true },
            {
                toggleScout: (state, { scout }) =>
                    state.includes(scout) ? state.filter((s) => s !== scout) : [...state, scout],
                clearScoutFilter: () => [],
                setFilters: (_, { filters }) => filters.scoutFilter,
                clearFilters: () => [],
            },
        ],
        priorityFilter: [
            [] as SignalReportPriority[],
            { persist: true },
            {
                togglePriority: (state, { priority }) =>
                    state.includes(priority) ? state.filter((p) => p !== priority) : [...state, priority],
                setPriorityFilter: (_, { priorities }) => priorities,
                setFilters: (_, { filters }) => filters.priorityFilter,
                clearFilters: () => [],
            },
        ],
        stateFilter: [
            DEFAULT_STATE_FILTER,
            { persist: true },
            {
                toggleState: (current, { state }) =>
                    current.includes(state) ? current.filter((s) => s !== state) : [...current, state],
                setFilters: (_, { filters }) => filters.stateFilter,
                clearFilters: () => DEFAULT_STATE_FILTER,
            },
        ],
    }),

    selectors({
        // Whether any server-side list-narrowing filter is active. Scope and sort are excluded: they
        // don't hide reports the way search/source/priority do, and `clearFilters` leaves them
        // untouched. The state filter is also excluded: it only narrows which states the flat
        // Reports list renders (client-side, redesign only), so the surfaces that need it check
        // `stateFilter` directly.
        hasActiveFilters: [
            (s) => [s.searchQuery, s.sourceProductFilter, s.scoutFilter, s.priorityFilter],
            (
                searchQuery: string,
                sourceProductFilter: string[],
                scoutFilter: string[],
                priorityFilter: SignalReportPriority[]
            ): boolean =>
                searchQuery.trim().length > 0 ||
                sourceProductFilter.length > 0 ||
                scoutFilter.length > 0 ||
                priorityFilter.length > 0,
        ],
        isRedesign: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => isInboxRedesignEnabled(featureFlags),
        ],
        isPersonalInboxEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.SIGNALS_PERSONAL_INBOX],
        ],
        isRelevanceSortAvailable: [
            (s) => [s.isPersonalInboxEnabled, s.scope],
            (isPersonalInboxEnabled: boolean, scope: InboxScope): boolean =>
                isPersonalInboxEnabled && scope === INBOX_SCOPE_FOR_YOU,
        ],
        // The sort the list and the Sort control use. Read this, not the stored `sortField` and
        // `sortDirection`, which hold the user's last pick.
        activeSort: [
            (s) => [s.sortField, s.sortDirection, s.hasUserChosenSort, s.isRelevanceSortAvailable],
            (
                sortField: InboxListSortField,
                sortDirection: InboxSortDirection,
                hasUserChosenSort: boolean,
                relevanceAvailable: boolean
            ): InboxSort => resolveInboxSort({ sortField, sortDirection, hasUserChosenSort, relevanceAvailable }),
        ],
        // The stored state filter can name states the current user cannot see: a staff-only state
        // from a shared link, or one persisted before staff access changed. The list and the filter
        // control read this narrowed view, so a hidden state can never strand the list on a
        // selection the control has no checkbox to clear. The raw `stateFilter` stays stored and in
        // the URL, so a staff user opening the same link still gets the full selection.
        visibleStateFilter: [
            (s) => [s.stateFilter, s.user],
            (stateFilter: InboxReportSectionKey[], user: UserType | null): InboxReportSectionKey[] =>
                user?.is_staff
                    ? stateFilter
                    : stateFilter.filter((key) => !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)),
        ],
    }),

    actionToUrl(({ values }) => {
        // Every filter mutation rewrites the current URL from the full (non-default) filter state.
        const toUrl = (): [string, Record<string, any>, any, { replace: boolean }] => currentUrlWithFilters(values)
        // `setFilters` is intentionally absent: it only fires while hydrating from the URL, which is
        // already the source of truth in that path, so re-deriving the URL from it would be redundant.
        return {
            setScope: toUrl,
            applyDefaultScope: toUrl,
            setSort: toUrl,
            toggleSourceProduct: toUrl,
            toggleScout: toUrl,
            clearScoutFilter: toUrl,
            togglePriority: toUrl,
            setPriorityFilter: toUrl,
            toggleState: toUrl,
            setSearchQuery: toUrl,
            clearFilters: toUrl,
        }
    }),

    urlToAction(({ actions, values }) => {
        const applyFromUrl = (_: unknown, searchParams: Record<string, any>): void => {
            const hasFilterParams = FILTER_URL_KEYS.some((key) => key in searchParams)
            if (!hasFilterParams) {
                // Bare inbox URL: keep the persisted state, but reflect any non-default filters back
                // into the URL so the current view is immediately shareable.
                const desired = filterSearchParams(values)
                if (Object.keys(desired).length > 0) {
                    router.actions.replace(
                        router.values.location.pathname,
                        { ...router.values.searchParams, ...desired },
                        router.values.hashParams
                    )
                }
                return
            }

            // A shared link is authoritative: apply the params it carries and reset the rest to defaults.
            // Only dispatch when something actually changed — urlToAction also fires on plain navigation
            // (opening a report, switching tabs), and we don't want a redundant list refresh each time.
            const parsed = parseFilterSearchParams(searchParams)
            const changed =
                values.scope !== parsed.scope ||
                !sameSet(values.sourceProductFilter, parsed.sourceProductFilter) ||
                !sameSet(values.scoutFilter, parsed.scoutFilter) ||
                !sameSet(values.priorityFilter, parsed.priorityFilter) ||
                !sameSet(values.stateFilter, parsed.stateFilter) ||
                values.sortField !== parsed.sortField ||
                values.sortDirection !== parsed.sortDirection ||
                values.hasUserChosenSort !== parsed.hasUserChosenSort ||
                values.searchQuery !== parsed.searchQuery
            if (changed) {
                actions.setFilters(parsed)
            }
        }

        return {
            [urls.inbox()]: applyFromUrl,
            [urls.inbox(':tab')]: applyFromUrl,
            [urls.inboxScratchpad()]: applyFromUrl,
            [urls.inboxFindings()]: applyFromUrl,
            [urls.inboxRuns()]: applyFromUrl,
            [urls.inboxTriage()]: applyFromUrl,
            [urls.inboxScout(':skillName')]: applyFromUrl,
            [urls.inboxScout(':skillName', ':findingId')]: applyFromUrl,
            [urls.inboxReport(':tab', ':reportId')]: applyFromUrl,
        }
    }),

    afterMount(({ actions }) => {
        actions.loadAvailableReviewers()
    }),
])
