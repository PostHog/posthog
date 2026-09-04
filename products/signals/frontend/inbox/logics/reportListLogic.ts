import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { derivePrState } from 'lib/signals/prState'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import { captureInboxReportAction, type InboxReportActionSurface } from '../inboxAnalytics'
import {
    ACTIONABLE_ACTIONABILITY_VALUES,
    INBOX_LEGACY_PRIMARY_REPORT_SECTION_KEY,
    INBOX_PRIMARY_REPORT_SECTION_KEY,
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    INBOX_LEGACY_TAB_SECTION,
    InboxFlatListTabKey,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
} from '../types'
import type { SignalReportPriority } from '../types'
import { DismissalFeedback, ResolveReasonValue, suppressDismissalPayload } from '../utils/dismissalReasons'
import { isInboxRedesignEnabled } from '../utils/inboxRedesign'
import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'
import { buildSignalReportListOrdering, inboxFiltersLogic } from './inboxFiltersLogic'
import type { InboxFilterState, InboxSortDirection, InboxSortField } from './inboxFiltersLogic'
import { prCiStatusLogic } from './prCiStatusLogic'

const PAGE_SIZE = 50

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
    // Fixed by a merged implementation PR, or resolved by a person. Terminal, not restorable.
    resolved: { status: 'resolved' },
    // Dismissed by a person, or suppressed because its PR closed without merging. Restorable.
    dismissed: { status: 'suppressed' },
    'not-actionable': { actionability: 'not_actionable' },
}

/** Logic props for one report state's keyed instance, shared by the flat Reports list consumers. */
export function sectionListLogicProps(sectionKey: InboxReportSectionKey): ReportListLogicProps {
    return { sectionKey, listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey] }
}

/**
 * The keyed list instance behind a legacy tab (redesign flag off). Every tab shows one section with
 * that section's filter, except Archive, which lists resolved and dismissed reports together. It
 * reuses the `resolved` instance with a wider filter instead of adding a section key, because the
 * section keys drive analytics, `data-attr` values, and persisted collapsed state that the legacy
 * tab must not extend, and the two layouts are never mounted together.
 */
export function legacyTabListLogicProps(tabKey: InboxFlatListTabKey): ReportListLogicProps {
    const sectionKey = INBOX_LEGACY_TAB_SECTION[tabKey]
    if (tabKey === 'archived') {
        return { sectionKey, listParams: { status: 'suppressed,resolved' } }
    }
    return { sectionKey, listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey] }
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
 * primary section (Needs decision under the redesign, the Pull requests list with the flag off) when
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
    isLoaded: boolean
    listApiParams: any
    loadedContext: {
        hasActiveFilters: boolean
        scope: InboxScope
    } | null
    loadedQueryKey: string | null
    openPrReportIds: string[]
    pageLoadFailed: boolean
    primarySectionKey: InboxReportSectionKey
    reports: SignalReport[]
    reportsLoadFailed: boolean
    reportsResponse: ReportListResponse | null
    reportsResponseLoading: boolean
    totalCount: number | null
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
    trackReports: (
        source: string,
        reportIds: string[]
    ) => {
        reportIds: string[]
        source: string
    } // prCiStatusLogic
    dismissReport: (
        reportId: string,
        dismissal: DismissalFeedback
    ) => {
        dismissal: DismissalFeedback
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
    resolveReport: (
        reportId: string,
        reason: ResolveReasonValue,
        note: string
    ) => {
        note: string
        reason: 'already_fixed' | 'fixed_outside_posthog' | 'other' | 'pr_merged'
        reportId: string
    }
    restoreReport: (
        reportId: string,
        surface: InboxReportActionSurface
    ) => {
        reportId: string
        surface: InboxReportActionSurface
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicMeta {
    key: 'dismissed' | 'monitoring' | 'needs-decision' | 'not-actionable' | 'resolved'
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
        hasMore: (reportsResponse: ReportListResponse | null) => boolean
        isLoaded: (reportsResponse: ReportListResponse | null) => boolean
        openPrReportIds: (reports: SignalReport[]) => string[]
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
 * Keyed per-state report list. Mounted once per report state (Review and merge / Needs decision /
 * Resolved / Dismissed / Not actionable), each with its own fixed `listParams`, so every state is
 * its own filtered request with its own accurate `count` and its own pagination. The shared user
 * chrome (search, sort, source, priority, reviewer scope) is connected from `inboxFiltersLogic` and
 * applied on top, so one filter row drives all of them. The flat Reports list merges the loaded
 * rows of the states the user selected; the legacy tabs render one instance each.
 *
 * `count` loads on mount (cheap `limit=1`) so state counts are available before any rows are. The
 * rows load lazily (`ensureLoaded`) only once a surface actually renders the state.
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
            prCiStatusLogic,
            ['trackReports'],
        ],
    })),

    actions({
        ensureLoaded: true,
        loadMore: true,
        dismissReport: (reportId: string, dismissal: DismissalFeedback) => ({ reportId, dismissal }),
        resolveReport: (reportId: string, reason: ResolveReasonValue, note: string) => ({ reportId, reason, note }),
        restoreReport: (reportId: string, surface: InboxReportActionSurface) => ({ reportId, surface }),
        removeReport: (reportId: string) => ({ reportId }),
        refresh: true,
    }),

    loaders(({ values }) => ({
        // Cheap count-only request – populates the state's count before its rows load. `count_only`
        // lets the backend answer with one `COUNT(*)`, skipping ordering, row serialization, and
        // the per-row metadata lookups.
        count: [
            null as number | null,
            {
                loadCount: async () => {
                    const response = await api.signalReports.list({
                        ...values.listApiParams,
                        limit: 1,
                        count_only: 'true',
                    })
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
            // A page response carries the same query's total, so reuse it instead of letting the
            // separately-loaded count disagree with the rows on screen.
            loadReportsSuccess: (_, { reportsResponse }) => reportsResponse.count,
            loadMoreReportsSuccess: (_, { reportsResponse }) => reportsResponse.count,
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
        // A next-page fetch failed. The loaded rows and `hasMore` are unchanged, and the scroll
        // sentinel may sit inside the viewport without re-firing, so the list must offer an explicit
        // retry. Cleared when a page request starts or lands.
        pageLoadFailed: [
            false,
            {
                loadReports: () => false,
                loadMoreReports: () => false,
                loadMoreReportsSuccess: () => false,
                loadMoreReportsFailure: () => true,
            },
        ],
    }),

    selectors({
        // The section whose For-you count decides the default scope: Needs decision under the redesign,
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
        hasMore: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean =>
                reportsResponse?.next !== null && reportsResponse?.next !== undefined,
        ],
        isLoaded: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean => reportsResponse !== null,
        ],
        // The loaded rows whose pull request is still open, so the pill can say whether CI is red.
        // A merged or closed pull request is left out: its checks are history, not something to act on.
        openPrReportIds: [
            (s) => [s.reports],
            (reports: SignalReport[]): string[] =>
                reports
                    .filter(
                        (report) =>
                            !!report.implementation_pr_url &&
                            derivePrState(report.status, report.implementation_pr_merged === true) === 'open'
                    )
                    .map((report) => report.id),
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
        // Announce this section's open pull requests so their CI state is resolved in one batch. Both
        // loaders report: the first page and each appended page bring rows that need painting. An
        // empty announcement matters too, because it retires the rows a narrowed filter dropped.
        loadReportsSuccess: () => actions.trackReports(props.sectionKey, values.openPrReportIds),
        loadMoreReportsSuccess: () => actions.trackReports(props.sectionKey, values.openPrReportIds),
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
        dismissReport: async ({ reportId, dismissal }) => {
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, {
                    state: 'suppressed',
                    ...suppressDismissalPayload(dismissal),
                })
                // Reconcile every mounted section against the server so the Dismissed target gains the
                // row and count, not just this source section (which already dropped it optimistically).
                inboxBulkActionsLogic.actions.reportStateChanged()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to dismiss report')
                actions.refresh()
            }
        },
        // Mark a report done without an inbox PR (transition to `resolved`). Optimistically drops it
        // from this section; the broadcast below reconciles every section, so it joins Resolved now.
        resolveReport: async ({ reportId, reason, note }) => {
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, {
                    state: 'resolved',
                    dismissal_reason: reason,
                    ...(note ? { dismissal_note: note } : {}),
                })
                lemonToast.success('Report resolved')
                // Reconcile every mounted section so the Resolved target gains the row and count.
                inboxBulkActionsLogic.actions.reportStateChanged()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to resolve report')
                actions.refresh()
            }
        },
        // Restore a suppressed report back to the inbox (transition to `potential`). Optimistically
        // drops it from Dismissed; the report re-enters the pipeline and resurfaces elsewhere.
        restoreReport: async ({ reportId, surface }) => {
            const report = values.reports.find((r) => r.id === reportId)
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, { state: 'potential' })
                // Fire only after the restore persists, matching ReportDetailActions' fallback path.
                captureInboxReportAction({ report, actionType: 'restore', surface })
                lemonToast.success('Report restored to inbox')
                // Restore maps through restore_target_status server-side, so the report lands back in
                // whichever section its pre-suppression status names (a report suppressed while ready
                // returns to Needs decision / Review and merge). Broadcast so every mounted section
                // reconciles — this one loses the row, the destination gains it and its count — not
                // just the section that owns the action.
                inboxBulkActionsLogic.actions.reportStateChanged()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to restore report')
                actions.refresh()
            }
        },
        // A bulk dismiss or resolve happens in the singleton; refresh this section once it lands so
        // the affected reports leave it and the counts settle.
        [inboxBulkActionsLogic.actionTypes.bulkDismissSuccess]: () => actions.refresh(),
        [inboxBulkActionsLogic.actionTypes.bulkResolveSuccess]: () => actions.refresh(),
        // A single report dismissed, resolved, or refunded elsewhere (e.g. the detail pane) – reconcile
        // this section against the server so the report leaves its section and joins Resolved or
        // Dismissed, counts included.
        [inboxBulkActionsLogic.actionTypes.reportStateChanged]: () => actions.refresh(),
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCount()
        },
    })),
])
