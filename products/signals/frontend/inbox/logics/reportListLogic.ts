import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import { captureInboxReportAction } from '../inboxAnalytics'
import {
    ACTIONABLE_ACTIONABILITY_VALUES,
    INBOX_LEGACY_PRIMARY_REPORT_SECTION_KEY,
    INBOX_PRIMARY_REPORT_SECTION_KEY,
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
} from '../types'
import type { SignalReportPriority } from '../types'
import { DismissalReasonValue } from '../utils/dismissalReasons'
import { isInboxRedesignEnabled } from '../utils/inboxRedesign'
import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'
import { buildSignalReportListOrdering, inboxFiltersLogic } from './inboxFiltersLogic'
import type { InboxFilterState, InboxSortDirection, InboxSortField } from './inboxFiltersLogic'

const PAGE_SIZE = 50

/**
 * How many rows a section shows before "Show more". Sections stack in one column, so each one has
 * to stay short enough that the sections below it are still reachable without scrolling past a
 * whole list. Well under the server `PAGE_SIZE`, so the first few "Show more" presses are free.
 */
// Annotated rather than inferred: kea-typegen reads a bare `= 5` as the literal type `5` and
// types the reducer it defaults as `5`, which then rejects the widened value.
export const SECTION_PAGE_SIZE: number = 5

/** Fixed, section-defining server filter (e.g. `{ has_implementation_pr: 'true' }`). */
export type ReportListParams = Record<string, string>

/** A list response stamped with the query params and display context that produced it (see the loader). */
export type ReportListResponse = CountedPaginatedResponse<SignalReport> & {
    requestParams?: Record<string, unknown>
    requestContext?: { scope: InboxScope; hasActiveFilters: boolean }
}

export interface ReportListLogicProps {
    sectionKey: InboxReportSectionKey
    /** The section's fixed server filter. User-driven chrome (search/sort/source/priority/scope) layers on top. */
    listParams: ReportListParams
}

/**
 * The fixed server filter per report section – the single source of truth shared by the section
 * bodies, the header counts, and the scene.
 */
export const INBOX_REPORT_SECTION_LIST_PARAMS: Record<InboxReportSectionKey, ReportListParams> = {
    // An implementation PR is open, waiting to be reviewed and merged.
    monitoring: { has_implementation_pr: 'true', status: 'ready' },
    // Researched and actionable, but no PR has been opened for it yet.
    'needs-decision': {
        has_implementation_pr: 'false',
        status: 'ready,pending_input',
        actionability: ACTIONABLE_ACTIONABILITY_VALUES.join(','),
    },
    // Terminal reports: ones resolved by a merged implementation PR (not restorable) and ones
    // the user archived (suppressed, restorable).
    resolved: { status: 'suppressed,resolved' },
    'not-actionable': { actionability: 'not_actionable' },
}

function teammateUuidFromScope(scope: string): string | undefined {
    return scope.startsWith('teammate:') ? scope.slice('teammate:'.length).trim() || undefined : undefined
}

/** Display context at request time, stamped onto the response for telemetry (mirrors `hasActiveFilters`). */
function requestContextFromValues(values: {
    scope: InboxScope
    searchQuery: string
    sourceProductFilter: string[]
    scoutFilter: string[]
    priorityFilter: SignalReportPriority[]
}): { scope: InboxScope; hasActiveFilters: boolean } {
    return {
        scope: values.scope,
        hasActiveFilters:
            values.searchQuery.trim().length > 0 ||
            values.sourceProductFilter.length > 0 ||
            values.scoutFilter.length > 0 ||
            values.priorityFilter.length > 0,
    }
}

/**
 * Whether to auto-switch the reviewer scope to Entire project on first load. True only for the
 * primary section (Needs a PR under the redesign, the Pull requests list with the flag off) when
 * the user is still on the (default) For-you scope, hasn't chosen a scope themselves, has resolved
 * to a real user, and has zero reports suggested to them — so a user with nothing assigned doesn't
 * land on an empty inbox. Pure so the branching is unit-testable without mounting the logic.
 */
export function shouldDefaultToEntireProject(input: {
    sectionKey: InboxReportSectionKey
    primarySectionKey: InboxReportSectionKey
    scope: InboxScope
    hasUserChosenScope: boolean
    hasResolvedUser: boolean
    count: number | null
}): boolean {
    return (
        input.sectionKey === input.primarySectionKey &&
        input.scope === INBOX_SCOPE_FOR_YOU &&
        !input.hasUserChosenScope &&
        input.hasResolvedUser &&
        input.count === 0
    )
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    hasUserChosenScope: boolean // inboxFiltersLogic
    priorityFilter: SignalReportPriority[] // inboxFiltersLogic
    scope: InboxScope // inboxFiltersLogic
    scoutFilter: string[] // inboxFiltersLogic
    searchQuery: string // inboxFiltersLogic
    sortDirection: InboxSortDirection // inboxFiltersLogic
    sortField: InboxSortField // inboxFiltersLogic
    sourceProductFilter: string[] // inboxFiltersLogic
    user: UserType | null // userLogic
    count: number | null
    countLoading: boolean
    hasMore: boolean
    hiddenReportCount: number
    isLoaded: boolean
    listApiParams: any
    loadedContext: {
        hasActiveFilters: boolean
        scope: InboxScope
    } | null
    loadedQueryKey: string | null
    primarySectionKey: InboxReportSectionKey
    reports: SignalReport[]
    reportsLoadFailed: boolean
    reportsResponse: ReportListResponse | null
    reportsResponseLoading: boolean
    totalCount: number | null
    visibleCount: number
    visibleReports: SignalReport[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicActions {
    applyDefaultScope: (scope: InboxScope) => {
        scope: InboxScope
    } // inboxFiltersLogic
    clearFilters: () => {
        value: true
    } // inboxFiltersLogic
    setFilters: (filters: InboxFilterState) => {
        filters: InboxFilterState
    } // inboxFiltersLogic
    setPriorityFilter: (priorities: SignalReportPriority[]) => {
        priorities: SignalReportPriority[]
    } // inboxFiltersLogic
    setScope: (scope: InboxScope) => {
        scope: InboxScope
    } // inboxFiltersLogic
    setSearchQuery: (searchQuery: string) => {
        searchQuery: string
    } // inboxFiltersLogic
    setSort: (
        field: InboxSortField,
        direction: InboxSortDirection
    ) => {
        direction: InboxSortDirection
        field: InboxSortField
    } // inboxFiltersLogic
    togglePriority: (priority: SignalReportPriority) => {
        priority: SignalReportPriority
    } // inboxFiltersLogic
    toggleScout: (scout: string) => {
        scout: string
    } // inboxFiltersLogic
    toggleSourceProduct: (source: string) => {
        source: string
    } // inboxFiltersLogic
    archiveReport: (
        reportId: string,
        reason: DismissalReasonValue,
        note: string
    ) => {
        note: string
        reason:
            | 'already_fixed'
            | 'analysis_wrong'
            | 'other'
            | 'report_unclear'
            | 'wontfix_intentional'
            | 'wontfix_irrelevant'
        reportId: string
    }
    ensureLoaded: () => {
        value: true
    }
    loadCount: () => any
    loadCountFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCountSuccess: (
        count: number,
        payload?: any
    ) => {
        count: number
        payload?: any
    }
    loadMore: () => {
        value: true
    }
    loadMoreReports: () => any
    loadMoreReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadMoreReportsSuccess: (
        reportsResponse: ReportListResponse,
        payload?: any
    ) => {
        reportsResponse: ReportListResponse
        payload?: any
    }
    loadReports: () => any
    loadReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportsSuccess: (
        reportsResponse: ReportListResponse,
        payload?: any
    ) => {
        reportsResponse: ReportListResponse
        payload?: any
    }
    refresh: () => {
        value: true
    }
    removeReport: (reportId: string) => {
        reportId: string
    }
    restoreReport: (reportId: string) => {
        reportId: string
    }
    showMore: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicMeta {
    key: 'monitoring' | 'needs-decision' | 'not-actionable' | 'resolved'
    __keaTypeGenInternalSelectorTypes: {
        primarySectionKey: (featureFlags: FeatureFlagsSet) => InboxReportSectionKey
        listApiParams: (
            searchQuery: string,
            sortField: InboxSortField,
            sortDirection: InboxSortDirection,
            sourceProductFilter: string[],
            scoutFilter: string[],
            priorityFilter: SignalReportPriority[],
            scope: InboxScope,
            user: UserType | null,
            arg: any
        ) => any
        reports: (reportsResponse: ReportListResponse | null) => SignalReport[]
        visibleReports: (reports: SignalReport[], visibleCount: number) => SignalReport[]
        hiddenReportCount: (totalCount: number | null, count: number | null, visibleReports: SignalReport[]) => number
        hasMore: (reportsResponse: ReportListResponse | null) => boolean
        isLoaded: (reportsResponse: ReportListResponse | null) => boolean
        totalCount: (reportsResponse: ReportListResponse | null) => number | null
        loadedQueryKey: (reportsResponse: ReportListResponse | null) => string | null
        loadedContext: (reportsResponse: ReportListResponse | null) => {
            hasActiveFilters: boolean
            scope: InboxScope
        } | null
    }
}

export type reportListLogicType = MakeLogicType<
    reportListLogicValues,
    reportListLogicActions,
    ReportListLogicProps,
    reportListLogicMeta
>

/**
 * Keyed per-section report list. Mounted once per Reports section (Review and merge / Needs a PR /
 * Resolved / Not actionable), each with its own fixed `listParams`, so every section is its own
 * filtered request with its own accurate `count` and its own pagination. The shared user chrome
 * (search, sort, source, priority, reviewer scope) is connected from `inboxFiltersLogic` and applied
 * on top, so one filter row drives all four.
 *
 * `count` loads on mount (cheap `limit=1`) so a section header is correct even while collapsed. The
 * rows load lazily (`ensureLoaded`) only once the section is expanded.
 */
export const reportListLogic = kea<reportListLogicType>([
    path((sectionKey) => ['scenes', 'inbox', 'logics', 'reportListLogic', sectionKey]),
    props({} as ReportListLogicProps),
    key((props) => props.sectionKey),

    connect(() => ({
        values: [
            inboxFiltersLogic,
            [
                'scope',
                'hasUserChosenScope',
                'searchQuery',
                'sortField',
                'sortDirection',
                'sourceProductFilter',
                'scoutFilter',
                'priorityFilter',
            ],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            inboxFiltersLogic,
            [
                'setSearchQuery',
                'setSort',
                'toggleSourceProduct',
                'toggleScout',
                'togglePriority',
                'setPriorityFilter',
                'setScope',
                'applyDefaultScope',
                'setFilters',
                'clearFilters',
            ],
        ],
    })),

    actions({
        ensureLoaded: true,
        loadMore: true,
        archiveReport: (reportId: string, reason: DismissalReasonValue, note: string) => ({ reportId, reason, note }),
        restoreReport: (reportId: string) => ({ reportId }),
        removeReport: (reportId: string) => ({ reportId }),
        refresh: true,
        showMore: true,
    }),

    loaders(({ values }) => ({
        // Cheap count-only request (limit=1) – populates the section header before its rows load.
        count: [
            null as number | null,
            {
                loadCount: async () => {
                    const response = await api.signalReports.list({ ...values.listApiParams, limit: 1 })
                    return response.count
                },
            },
        ],
        reportsResponse: [
            null as ReportListResponse | null,
            {
                // `requestParams` records the query that produced the response, so consumers
                // (impression telemetry) can key off what was actually fetched rather than the
                // live `listApiParams`, which changes before the refetch lands.
                loadReports: async (): Promise<ReportListResponse> => {
                    const params = values.listApiParams
                    const requestContext = requestContextFromValues(values)
                    const response = await api.signalReports.list({ ...params, offset: 0, limit: PAGE_SIZE })
                    return { ...response, requestParams: params, requestContext }
                },
                loadMoreReports: async (): Promise<ReportListResponse> => {
                    const params = values.listApiParams
                    const requestContext = requestContextFromValues(values)
                    const current = values.reportsResponse?.results ?? []
                    const response = await api.signalReports.list({
                        ...params,
                        offset: current.length,
                        limit: PAGE_SIZE,
                    })
                    return {
                        ...response,
                        results: [...current, ...response.results],
                        requestParams: params,
                        requestContext,
                    }
                },
            },
        ],
    })),

    reducers({
        reportsResponse: {
            // Optimistic removal on archive – keeps the list snappy; count refreshes in the background.
            removeReport: (state, { reportId }) =>
                state
                    ? {
                          ...state,
                          results: state.results.filter((r) => r.id !== reportId),
                          count: Math.max(0, state.count - 1),
                      }
                    : state,
        },
        count: {
            removeReport: (state) => (state != null ? Math.max(0, state - 1) : state),
        },
        // The first-page load failed. Kea loaders keep `reportsResponse` null on failure, so
        // `isLoaded` stays false and the section would otherwise show a skeleton forever. Reset when a
        // load starts or lands, so a retry clears the error. Keyed on the first-page loader only — a
        // failed `loadMoreReports` keeps the loaded rows, so it must not flag the whole section.
        reportsLoadFailed: [
            false,
            {
                loadReports: () => false,
                loadReportsSuccess: () => false,
                loadReportsFailure: () => true,
            },
        ],
        // How many of the loaded rows this section renders. Reset whenever the list is re-fetched
        // from the top (first load, refresh, any filter change), so a new query starts short again.
        visibleCount: [
            SECTION_PAGE_SIZE,
            {
                showMore: (state) => state + SECTION_PAGE_SIZE,
                loadReports: () => SECTION_PAGE_SIZE,
            },
        ],
    }),

    selectors({
        // The section whose For-you count decides the default scope: Needs a PR under the redesign,
        // the Pull requests list with the flag off (see `shouldDefaultToEntireProject`).
        primarySectionKey: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): InboxReportSectionKey =>
                isInboxRedesignEnabled(featureFlags)
                    ? INBOX_PRIMARY_REPORT_SECTION_KEY
                    : INBOX_LEGACY_PRIMARY_REPORT_SECTION_KEY,
        ],
        // The section's fixed filter merged with the user-driven chrome + reviewer scope (server-side).
        listApiParams: [
            (s) => [
                s.searchQuery,
                s.sortField,
                s.sortDirection,
                s.sourceProductFilter,
                s.scoutFilter,
                s.priorityFilter,
                s.scope,
                s.user,
                (_, p) => p.listParams,
            ],
            (
                searchQuery: string,
                sortField: import('./inboxFiltersLogic').InboxSortField,
                sortDirection: import('./inboxFiltersLogic').InboxSortDirection,
                sourceProductFilter: string[],
                scoutFilter: string[],
                priorityFilter: import('../types').SignalReportPriority[],
                scope: InboxScope,
                user: null | import('~/types').UserType,
                listParams
            ) => {
                const suggestedReviewer =
                    scope === INBOX_SCOPE_FOR_YOU ? (user?.uuid ?? undefined) : teammateUuidFromScope(scope)
                return {
                    ...listParams,
                    search: searchQuery.trim() || undefined,
                    ordering: buildSignalReportListOrdering(sortField, sortDirection),
                    source_product: sourceProductFilter.length > 0 ? sourceProductFilter.join(',') : undefined,
                    scout: scoutFilter.length > 0 ? scoutFilter.join(',') : undefined,
                    priority: priorityFilter.length > 0 ? priorityFilter.join(',') : undefined,
                    suggested_reviewers: suggestedReviewer,
                }
            },
        ],
        reports: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): SignalReport[] => reportsResponse?.results ?? [],
        ],
        // The rows the section actually renders.
        visibleReports: [
            (s) => [s.reports, s.visibleCount],
            (reports: SignalReport[], visibleCount: number): SignalReport[] => reports.slice(0, visibleCount),
        ],
        /**
         * How many matching reports this section is holding back — what "Show more" promises. Reads
         * the loaded response's own total first so it can't disagree with the rows on screen; the
         * separately-loaded header count is the fallback while the first page is still in flight.
         * Subtract the rows actually on screen (`visibleReports.length`), not the window size
         * (`visibleCount`): "Show more" widens the window past the loaded rows before the next page
         * lands, so a page still in flight or one that failed to load leaves `visibleCount` ahead of
         * `reports.length`. Using the window size there would drive this to 0 and unmount the button,
         * stranding the unloaded rows with no way to retry.
         */
        hiddenReportCount: [
            (s) => [s.totalCount, s.count, s.visibleReports],
            (totalCount: number | null, count: number | null, visibleReports: SignalReport[]): number =>
                Math.max(0, (totalCount ?? count ?? 0) - visibleReports.length),
        ],
        hasMore: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean =>
                reportsResponse?.next !== null && reportsResponse?.next !== undefined,
        ],
        isLoaded: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean => reportsResponse !== null,
        ],
        // Total matching the *loaded* results — from the same response, so it can never be stale
        // relative to `reports` the way the separately-loaded badge `count` can (filter/refresh races).
        totalCount: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): number | null => reportsResponse?.count ?? null,
        ],
        // Stable key for the query that produced the loaded response. Unlike `listApiParams`, this
        // only changes when a response fetched with the new params actually lands, so consumers
        // never associate the new query with rows from the previous one.
        loadedQueryKey: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): string | null =>
                reportsResponse?.requestParams ? JSON.stringify(reportsResponse.requestParams) : null,
        ],
        // Display context (scope, active-filters flag) as it was when the loaded response was
        // requested — for telemetry, so an in-flight response can't be labeled with context the
        // user switched to after the request went out.
        loadedContext: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): { scope: InboxScope; hasActiveFilters: boolean } | null =>
                reportsResponse?.requestContext ?? null,
        ],
    }),

    listeners(({ actions, values, props }) => ({
        // First For-you count for the primary section: if the user has no reports suggested to
        // them, default to Entire project so they don't land on an empty inbox. Only when they haven't
        // picked a scope themselves, and only once the user's uuid has resolved (so the count is
        // genuinely theirs, not an unfiltered project-wide count).
        loadCountSuccess: () => {
            if (
                shouldDefaultToEntireProject({
                    sectionKey: props.sectionKey,
                    primarySectionKey: values.primarySectionKey,
                    scope: values.scope,
                    hasUserChosenScope: values.hasUserChosenScope,
                    hasResolvedUser: !!values.user?.uuid,
                    count: values.count,
                })
            ) {
                actions.applyDefaultScope(INBOX_SCOPE_ENTIRE_PROJECT)
            }
        },
        ensureLoaded: () => {
            if (values.reportsResponse === null && !values.reportsResponseLoading) {
                actions.loadReports()
            }
        },
        loadMore: () => {
            if (values.hasMore && !values.reportsResponseLoading) {
                actions.loadMoreReports()
            }
        },
        // The reducer has already widened the window. Only reach for another server page when the
        // window now extends past the rows in hand.
        showMore: () => {
            // The reducer already widened the window, so `hidden_count` is what is still held back.
            captureInboxReportAction({
                actionType: 'show_more',
                surface: 'list_row',
                extra: { section: props.sectionKey, hidden_count: values.hiddenReportCount },
            })
            if (values.visibleCount > values.reports.length) {
                actions.loadMore()
            }
        },
        refresh: () => {
            actions.loadCount()
            if (values.isLoaded) {
                actions.loadReports()
            }
        },
        // User-driven filter/scope changes re-fetch the count always, and the rows if this section is loaded.
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.refresh()
        },
        setSort: () => actions.refresh(),
        toggleSourceProduct: () => actions.refresh(),
        toggleScout: () => actions.refresh(),
        togglePriority: () => actions.refresh(),
        setPriorityFilter: () => actions.refresh(),
        setScope: () => actions.refresh(),
        applyDefaultScope: () => actions.refresh(),
        setFilters: () => actions.refresh(),
        clearFilters: () => actions.refresh(),
        // For-you scope needs the current user's uuid; reload once it resolves.
        [userLogic.actionTypes.loadUserSuccess]: () => {
            if (values.scope === INBOX_SCOPE_FOR_YOU) {
                actions.refresh()
            }
        },
        archiveReport: async ({ reportId, reason, note }) => {
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, {
                    state: 'suppressed',
                    dismissal_reason: reason,
                    ...(note ? { dismissal_note: note } : {}),
                })
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to archive report')
                actions.refresh()
            }
        },
        // Restore a suppressed report back to the inbox (transition to `potential`). Optimistically
        // drops it from Resolved; the report re-enters the pipeline and resurfaces elsewhere.
        restoreReport: async ({ reportId }) => {
            const report = values.reports.find((r) => r.id === reportId)
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, { state: 'potential' })
                // Fire only after the restore persists, matching ReportDetailActions' fallback path.
                captureInboxReportAction({ report, actionType: 'restore', surface: 'list_row' })
                lemonToast.success('Report restored to inbox')
                // Restore maps through restore_target_status server-side, so a report suppressed while
                // resolved returns to `resolved` and still belongs in this section. Reconcile against
                // the server rather than trusting the optimistic removal, which over-drops those rows.
                actions.refresh()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to restore report')
                actions.refresh()
            }
        },
        // Bulk archive happens in the singleton; refresh this section once it lands.
        [inboxBulkActionsLogic.actionTypes.bulkDismissSuccess]: () => actions.refresh(),
        // A single report archived elsewhere (e.g. the detail pane) – reconcile this section against
        // the server so the report leaves its section and joins Resolved, counts included.
        [inboxBulkActionsLogic.actionTypes.reportArchived]: () => actions.refresh(),
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCount()
        },
    })),
])
