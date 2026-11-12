import { MakeLogicType, actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { ApiConfig, CountedPaginatedResponse } from 'lib/api'
import { ApiError } from 'lib/api-error'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { derivePrState } from 'lib/signals/prState'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import type { UserType } from '~/types'

import {
    signalsReportsRefreshMetricsCreate,
    signalsReportsList,
    signalsReportsReviewersMeCreate,
    signalsReportsReviewersMeDestroy,
    signalsReportsSourceMetadataCreate,
} from 'products/signals/frontend/generated/api'
import type {
    PaginatedSignalReportListListApi,
    PaginatedSignalReportListListApiPersonalRankingStatus,
    ReviewerRemovalReasonEnumApi,
    SignalReportMetricSnapshotsApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { SignalReportAssigneeApi } from '../../generated/api.schemas'
import { createdAfterForWindow, isMergeKeySortField } from '../filterOptions'
import { captureInboxReportAction, type InboxReportActionSurface, setInboxServedRanker } from '../inboxAnalytics'
import {
    INBOX_PRIMARY_REPORT_SECTION_KEY,
    INBOX_REPORT_SECTION_KEYS,
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_CLAIMED_BY_YOU,
    INBOX_SCOPE_FOR_YOU,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
} from '../types'
import type { SignalReportPriority } from '../types'
import { DismissalFeedback, ResolveReasonValue, suppressDismissalPayload } from '../utils/dismissalReasons'
import { requestReportClaim } from '../utils/reportClaim'
import { keepRowFieldsWrittenDuringFetch } from '../utils/reportFreshness'
import { isReportMetricsEnabled, mergeReportMetricSnapshots, reportNeedsMetricRefresh } from '../utils/reportMetrics'
import { reportPullRequests, primaryReportPullRequest } from '../utils/reportPullRequests'
import { setReportState } from '../utils/writeTimeout'
import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'
import { appliedInboxSearch, buildSignalReportListSortParams, inboxFiltersLogic } from './inboxFiltersLogic'
import type { InboxCreatedWindow, InboxFilterState, InboxSortDirection, InboxSortField } from './inboxFiltersLogic'
import { prCiStatusLogic } from './prCiStatusLogic'

const PAGE_SIZE = 50
const REPORT_LIST_RETRY_DELAY_MS = 300
// The refresh endpoint's own id cap per call.
const METRIC_REFRESH_PAGE_SIZE = 20

function isRetryableReportListError(error: unknown): boolean {
    return error instanceof ApiError && (error.status === undefined || error.status === 408 || error.status >= 500)
}

/** The row fields the list leaves empty (`include_source_metadata=false`) and `source_metadata` fills in. */
export type ReportSourceMeta = Pick<SignalReport, 'source_products' | 'scout_name'>

/** Fixed, section-defining server filter (e.g. `{ has_implementation_pr: 'true' }`). */
export type ReportListParams = Record<string, string>

/** Display context of the query that produced a response, for telemetry. */
export interface ReportListRequestContext {
    scope: InboxScope
    hasActiveFilters: boolean
    sortField: InboxSortField
    sortDirection: InboxSortDirection
    createdWindow: InboxCreatedWindow | null
}

/** A list response stamped with the query params and display context that produced it (see the loader). */
export type ReportListResponse = CountedPaginatedResponse<SignalReport> &
    Pick<PaginatedSignalReportListListApi, 'count_is_capped' | 'ranking_id' | 'personal_ranking_status'> & {
        /** The ranker the server used for `sort=recommended` or `sort=personal`. Null for every other sort. */
        ranker?: string | null
        /** Whether the client shows a ranking score pill on each card, for `sort=recommended` or `sort=personal`. Null for every other sort. */
        ranking_pill?: boolean | null
        requestParams?: Record<string, unknown>
        requestContext?: ReportListRequestContext
    }

/**
 * The list request for the API. `created_window` stays a preset key in `listApiParams`, so the
 * query key does not change every second, and turns into a `created_after` bound here, when the
 * request goes out.
 */
function listRequestParams({ created_window, ...params }: Record<string, any>): Record<string, any> {
    return { ...params, created_after: createdAfterForWindow(created_window ?? null) }
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
    'needs-decision': { view: 'needs_decision' },
    'outcome-monitoring': { status: 'monitoring' },
    // Fixed by a merged implementation PR, or resolved by a person. Terminal, not restorable.
    resolved: { status: 'resolved' },
    closed: { view: 'closed' },
    // Dismissed by a person or agent, or suppressed because its PR closed without merging. Restorable.
    dismissed: { view: 'dismissed' },
    // Suppressed by the safety or actionability judge, with no dismissal from anyone.
    'held-back': { view: 'held_back' },
    'not-actionable': { actionability: 'not_actionable' },
}

/** Logic props for one report state's keyed instance, shared by the flat Reports list consumers. */
export function sectionListLogicProps(sectionKey: InboxReportSectionKey): ReportListLogicProps {
    return { sectionKey, listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey] }
}

/** Whose personal ranking a list reads: the teammate of a Personalized list with a teammate scope, else the user. */
function personalRankingOwner(sortField: InboxSortField, teammateUuid: unknown): unknown {
    return sortField === 'personal' ? teammateUuid : undefined
}

/**
 * The personal ranking a state already loaded with. The flat list merges the states by
 * `inbox_merge_key`, and keys from two rankings do not compare. A state that loads later, such as one
 * the user selects after a rebuild, must request the same ranking as the states already on screen.
 * Only a ranking of the same owner counts: after a switch to or from a teammate scope, the states
 * still on screen hold another person's ranking.
 */
function loadedPersonalRankingId(sortField: InboxSortField, teammateUuid: string | undefined): string | undefined {
    const owner = personalRankingOwner(sortField, teammateUuid)
    for (const sectionKey of INBOX_REPORT_SECTION_KEYS) {
        const response = reportListLogic.findMounted(sectionListLogicProps(sectionKey))?.values.reportsResponse
        if (
            response?.ranker === 'personal' &&
            response.ranking_id &&
            response.requestContext &&
            personalRankingOwner(response.requestContext.sortField, response.requestParams?.teammate_uuid) === owner
        ) {
            return response.ranking_id
        }
    }
    return undefined
}

function teammateUuidFromScope(scope: string): string | undefined {
    return scope.startsWith('teammate:') ? scope.slice('teammate:'.length).trim() || undefined : undefined
}

/** Display context at request time, stamped onto the response for telemetry (mirrors `hasActiveFilters`). */
function requestContextFromValues(values: {
    scope: InboxScope
    searchQuery: string
    activeSourceProductFilter: string[]
    activeScoutFilter: string[]
    priorityFilter: SignalReportPriority[]
    activeSortField: InboxSortField
    activeSortDirection: InboxSortDirection
    activeCreatedWindow: InboxCreatedWindow | null
}): ReportListRequestContext {
    return {
        scope: values.scope,
        hasActiveFilters:
            appliedInboxSearch(values.searchQuery) !== undefined ||
            values.activeSourceProductFilter.length > 0 ||
            values.activeScoutFilter.length > 0 ||
            values.priorityFilter.length > 0 ||
            values.activeCreatedWindow !== null,
        sortField: values.activeSortField,
        sortDirection: values.activeSortDirection,
        createdWindow: values.activeCreatedWindow,
    }
}

/**
 * Whether to auto-switch the reviewer scope to Entire project on first load. True only for the
 * primary section (Needs decision) when
 * the user is still on the (default) For-you scope, hasn't chosen a scope themselves, has resolved
 * to a real user, and has zero reports suggested to them — so a user with nothing assigned doesn't
 * land on an empty inbox. Pure so the branching is unit-testable without mounting the logic.
 */
export function shouldDefaultToEntireProject(input: {
    sectionKey: InboxReportSectionKey
    scope: InboxScope
    hasUserChosenScope: boolean
    hasResolvedUser: boolean
    count: number | null
}): boolean {
    return (
        input.sectionKey === INBOX_PRIMARY_REPORT_SECTION_KEY &&
        input.scope === INBOX_SCOPE_FOR_YOU &&
        !input.hasUserChosenScope &&
        input.hasResolvedUser &&
        input.count === 0
    )
}

// First For-you count for the primary section: if the user has no reports suggested to
// them, default to Entire project so they don't land on an empty inbox. Only when they haven't
// picked a scope themselves, and only once the user's uuid has resolved (so the count is
// genuinely theirs, not an unfiltered project-wide count). A loaded section takes its count from
// its first page, so this runs on both counts.
function applyDefaultScopeIfEmpty(
    props: reportListLogicType['props'],
    values: reportListLogicType['values'],
    actions: reportListLogicType['actions']
): void {
    if (
        shouldDefaultToEntireProject({
            sectionKey: props.sectionKey,
            scope: values.scope,
            hasUserChosenScope: values.hasUserChosenScope,
            hasResolvedUser: !!values.user?.uuid,
            count: values.count,
        })
    ) {
        actions.applyDefaultScope(INBOX_SCOPE_ENTIRE_PROJECT)
    }
}

/**
 * A write that timed out or lost its response can still have saved, so every surface that shows the report reloads
 * it. This list can be mounted without the inbox scene, for example in a row menu, and then only reloads itself.
 */
function reloadAfterFailedWrite(reportId: string, refresh: () => void): void {
    const bulkActions = inboxBulkActionsLogic.findMounted()
    if (bulkActions) {
        bulkActions.actions.reportWriteFailed([reportId])
    } else {
        refresh()
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    activeCreatedWindow: InboxCreatedWindow | null // inboxFiltersLogic
    activeScoutFilter: string[] // inboxFiltersLogic
    activeSortDirection: InboxSortDirection // inboxFiltersLogic
    activeSortField: InboxSortField // inboxFiltersLogic
    activeSourceProductFilter: string[] // inboxFiltersLogic
    hasUserChosenScope: boolean // inboxFiltersLogic
    isScopedToMe: boolean // inboxFiltersLogic
    priorityFilter: SignalReportPriority[] // inboxFiltersLogic
    scope: InboxScope // inboxFiltersLogic
    searchQuery: string // inboxFiltersLogic
    currentTeamId: number | null // teamLogic
    user: UserType | null // userLogic
    claimSavingReportIds: string[]
    count: number | null
    countIsCapped: boolean
    countLoading: boolean
    countSettled: boolean
    hasMore: boolean
    hasProjectReports: boolean | null
    hasProjectReportsLoading: boolean
    isLoaded: boolean
    listApiParams: any
    livePrReportIds: string[]
    loadedContext: ReportListRequestContext | null
    loadedPersonalFallback: boolean
    loadedPersonalOrder: boolean
    loadedPersonalRankingStatus: PaginatedSignalReportListListApiPersonalRankingStatus
    loadedQueryKey: string | null
    loadedRanker: string | null
    loadedRankingPill: boolean
    pageLoadFailed: boolean
    reportSourceMeta: Record<string, ReportSourceMeta>
    reports: SignalReport[]
    reportsLoadFailed: boolean
    reportsResponse: ReportListResponse | null
    reportsResponseLoading: boolean
    scopeAssignee: 'mine' | undefined
    scopeReviewerUuid: string | undefined
    staleMetricReportIds: string[]
    totalCount: number | null
    unassigningReportIds: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicActions {
    applyDefaultCreatedWindow: (createdWindow: InboxCreatedWindow) => {
        createdWindow: InboxCreatedWindow
    } // inboxFiltersLogic
    applyDefaultScope: (scope: InboxScope) => {
        scope: InboxScope
    } // inboxFiltersLogic
    clearFilters: () => {
        value: true
    } // inboxFiltersLogic
    resetUnavailableSort: () => {
        value: true
    } // inboxFiltersLogic
    setCreatedWindow: (createdWindow: InboxCreatedWindow | null) => {
        createdWindow: InboxCreatedWindow | null
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
    setSourceFilter: (selection: null | import('./inboxFiltersLogic').InboxSourceSelection) => {
        selection: null | import('./inboxFiltersLogic').InboxSourceSelection
    } // inboxFiltersLogic
    sourceFilterAvailabilityChanged: () => {
        value: true
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
    applyReportMetricSnapshots: (snapshots: SignalReportMetricSnapshotsApi[]) => {
        snapshots: SignalReportMetricSnapshotsApi[]
    }
    applyReportSourceMeta: (meta: Record<string, ReportSourceMeta>) => {
        meta: Record<string, ReportSourceMeta>
    }
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
    loadCount: (_: void) => void
    loadCountFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCountSuccess: (
        count: number | null,
        payload?: void
    ) => {
        count: number | null
        payload?: void
    }
    loadHasProjectReports: (_: void) => void
    loadHasProjectReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadHasProjectReportsSuccess: (
        hasProjectReports: boolean,
        payload?: void
    ) => {
        hasProjectReports: boolean
        payload?: void
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
    loadReportSourceMeta: (reportIds: string[]) => {
        reportIds: string[]
    }
    loadReports: (_: void) => void
    loadReportsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportsSuccess: (
        reportsResponse: ReportListResponse,
        payload?: void
    ) => {
        reportsResponse: ReportListResponse
        payload?: void
    }
    refresh: () => {
        value: true
    }
    refreshReportMetrics: (reportIds: string[]) => {
        reportIds: string[]
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
        reason: ResolveReasonValue
        reportId: string
    }
    restoreReport: (
        reportId: string,
        surface: InboxReportActionSurface
    ) => {
        reportId: string
        surface: InboxReportActionSurface
    }
    setReportAssignee: (
        reportId: string,
        assignee: SignalReport['assignee']
    ) => {
        assignee: SignalReportAssigneeApi | null | undefined
        reportId: string
    }
    setReportClaimed: (
        report: SignalReport,
        claimed: boolean,
        surface: InboxReportActionSurface,
        takeover?: boolean
    ) => {
        claimed: boolean
        report: SignalReport
        surface: InboxReportActionSurface
        takeover: boolean
    }
    setReportClaimedFinished: (reportId: string) => {
        reportId: string
    }
    setSuggestedToMe: (
        reportIds: string[],
        isSuggested: boolean
    ) => {
        isSuggested: boolean
        reportIds: string[]
    }
    unassignMe: (
        reportId: string,
        surface: InboxReportActionSurface,
        reason?: ReviewerRemovalReasonEnumApi
    ) => {
        reason: ReviewerRemovalReasonEnumApi | undefined
        reportId: string
        surface: InboxReportActionSurface
    }
    unassignMeFinished: (reportId: string) => {
        reportId: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface reportListLogicMeta {
    key:
        | 'closed'
        | 'dismissed'
        | 'held-back'
        | 'monitoring'
        | 'needs-decision'
        | 'not-actionable'
        | 'outcome-monitoring'
        | 'resolved'
    __keaTypeGenInternalSelectorTypes: {
        scopeReviewerUuid: (scope: InboxScope, user: UserType | null) => string | undefined
        scopeAssignee: (scope: InboxScope) => 'mine' | undefined
        listApiParams: (
            searchQuery: string,
            activeSortField: InboxSortField,
            activeSortDirection: InboxSortDirection,
            activeSourceProductFilter: string[],
            activeScoutFilter: string[],
            priorityFilter: SignalReportPriority[],
            scopeReviewerUuid: string | undefined,
            scope: InboxScope,
            scopeAssignee: 'mine' | undefined,
            activeCreatedWindow: InboxCreatedWindow | null,
            arg: any
        ) => any
        reports: (
            reportsResponse: ReportListResponse | null,
            reportSourceMeta: Record<string, ReportSourceMeta>
        ) => SignalReport[]
        staleMetricReportIds: (reports: SignalReport[]) => string[]
        hasMore: (reportsResponse: ReportListResponse | null) => boolean
        isLoaded: (reportsResponse: ReportListResponse | null) => boolean
        livePrReportIds: (reports: SignalReport[]) => string[]
        totalCount: (reportsResponse: ReportListResponse | null) => number | null
        countIsCapped: (reportsResponse: ReportListResponse | null) => boolean
        loadedQueryKey: (reportsResponse: ReportListResponse | null) => string | null
        countSettled: (
            countLoading: boolean,
            reportsResponseLoading: boolean,
            reportsResponse: ReportListResponse | null,
            reportsLoadFailed: boolean,
            loadedQueryKey: string | null,
            listApiParams: any
        ) => boolean
        loadedContext: (reportsResponse: ReportListResponse | null) => ReportListRequestContext | null
        loadedRanker: (reportsResponse: ReportListResponse | null) => string | null
        loadedRankingPill: (reportsResponse: ReportListResponse | null) => boolean
        loadedPersonalOrder: (reportsResponse: ReportListResponse | null) => boolean
        loadedPersonalRankingStatus: (
            reportsResponse: ReportListResponse | null
        ) => PaginatedSignalReportListListApiPersonalRankingStatus
        loadedPersonalFallback: (reportsResponse: ReportListResponse | null) => boolean
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
 * rows of the states the user selected.
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
                'isScopedToMe',
                'hasUserChosenScope',
                'searchQuery',
                'activeSortField',
                'activeSortDirection',
                'activeSourceProductFilter',
                'activeScoutFilter',
                'priorityFilter',
                'activeCreatedWindow',
            ],
            userLogic,
            ['user'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeamId'],
        ],
        actions: [
            inboxFiltersLogic,
            [
                'setSearchQuery',
                'setSort',
                'resetUnavailableSort',
                'toggleSourceProduct',
                'toggleScout',
                'setSourceFilter',
                'sourceFilterAvailabilityChanged',
                'togglePriority',
                'setPriorityFilter',
                'setScope',
                'applyDefaultScope',
                'setFilters',
                'clearFilters',
                'setCreatedWindow',
                'applyDefaultCreatedWindow',
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
        unassignMe: (reportId: string, surface: InboxReportActionSurface, reason?: ReviewerRemovalReasonEnumApi) => ({
            reportId,
            surface,
            reason,
        }),
        unassignMeFinished: (reportId: string) => ({ reportId }),
        setReportClaimed: (
            report: SignalReport,
            claimed: boolean,
            surface: InboxReportActionSurface,
            takeover: boolean = false
        ) => ({
            report,
            claimed,
            surface,
            takeover,
        }),
        setReportClaimedFinished: (reportId: string) => ({ reportId }),
        setSuggestedToMe: (reportIds: string[], isSuggested: boolean) => ({ reportIds, isSuggested }),
        setReportAssignee: (reportId: string, assignee: SignalReport['assignee']) => ({ reportId, assignee }),
        removeReport: (reportId: string) => ({ reportId }),
        refresh: true,
        // Ask the server for the newest snapshot of the metrics these rows show. Best effort: a
        // failure leaves the rows on their saved snapshot.
        refreshReportMetrics: (reportIds: string[]) => ({ reportIds }),
        applyReportMetricSnapshots: (snapshots: SignalReportMetricSnapshotsApi[]) => ({ snapshots }),
        // Source products and scout come from ClickHouse, so the rows load without them and this
        // fills them in once the page is on screen. Best effort: a failure leaves the source line empty.
        loadReportSourceMeta: (reportIds: string[]) => ({ reportIds }),
        applyReportSourceMeta: (meta: Record<string, ReportSourceMeta>) => ({ meta }),
    }),

    loaders(({ values, cache, props }) => ({
        hasProjectReports: [
            null as boolean | null,
            {
                loadHasProjectReports: async (_: void, breakpoint) => {
                    const response = await signalsReportsList(String(values.currentTeamId), {
                        ...props.listParams,
                        count_only: true,
                        limit: 1,
                    })
                    breakpoint()
                    return response.count > 0
                },
            },
        ],
        // Cheap count-only request – populates the state's count before its rows load. `count_only`
        // lets the backend answer with one `COUNT(*)`, skipping ordering, row serialization, and
        // the per-row metadata lookups.
        count: [
            null as number | null,
            {
                loadCount: async (_: void, breakpoint) => {
                    const params = values.listApiParams
                    const pageAtRequest = values.reportsResponse
                    // nosemgrep: prefer-codegen-api-namespaced-signals -- the Inbox renders the handwritten SignalReport. The generated report type is wider (string status and priority, read-only arrays), so the list calls move to generated types together with the Inbox.
                    const response = await api.signalReports.list({
                        ...listRequestParams(params),
                        limit: 1,
                        count_only: 'true',
                    })
                    // A newer count request for a changed query supersedes this one.
                    breakpoint()
                    // A loaded section sends no new count request, so nothing else retires this
                    // one. Drop it when the query moved on, and when a page landed while it was in
                    // flight, because that page carries the total for the rows now on screen.
                    if (
                        JSON.stringify(values.listApiParams) !== JSON.stringify(params) ||
                        values.reportsResponse !== pageAtRequest
                    ) {
                        return values.count
                    }
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
                loadReports: async (_: void, breakpoint): Promise<ReportListResponse> => {
                    const params = values.listApiParams
                    const requestContext = requestContextFromValues(values)
                    cache.firstPageRequestId = (cache.firstPageRequestId ?? 0) + 1
                    const rowsBefore = values.reportsResponse?.results
                    const request = (): Promise<CountedPaginatedResponse<SignalReport>> =>
                        // nosemgrep: prefer-codegen-api-namespaced-signals -- the Inbox renders the handwritten SignalReport. The generated report type is wider (string status and priority, read-only arrays), so the list calls move to generated types together with the Inbox.
                        api.signalReports.list({
                            ...listRequestParams(params),
                            offset: 0,
                            limit: PAGE_SIZE,
                            ranking_id: isMergeKeySortField(requestContext.sortField)
                                ? loadedPersonalRankingId(requestContext.sortField, params.teammate_uuid)
                                : undefined,
                        })
                    let response: CountedPaginatedResponse<SignalReport>
                    try {
                        response = await request()
                    } catch (error) {
                        if (!isRetryableReportListError(error)) {
                            throw error
                        }
                        await breakpoint(REPORT_LIST_RETRY_DELAY_MS)
                        response = await request()
                    }
                    // A newer first-page request for a changed query supersedes this one.
                    breakpoint()
                    return {
                        ...response,
                        results: keepRowFieldsWrittenDuringFetch(
                            response.results,
                            rowsBefore,
                            values.reportsResponse?.results
                        ),
                        requestParams: params,
                        requestContext,
                    }
                },
                loadMoreReports: async (): Promise<ReportListResponse> => {
                    const params = values.listApiParams
                    const requestContext = requestContextFromValues(values)
                    const firstPageRequestId = cache.firstPageRequestId
                    const current = values.reportsResponse?.results ?? []
                    // nosemgrep: prefer-codegen-api-namespaced-signals -- the Inbox renders the handwritten SignalReport. The generated report type is wider (string status and priority, read-only arrays), so the list calls move to generated types together with the Inbox.
                    const response = await api.signalReports.list({
                        ...listRequestParams(params),
                        offset: current.length,
                        limit: PAGE_SIZE,
                        // A personal ranking rebuilt between pages would reorder the pages already on screen.
                        ranking_id: values.reportsResponse?.ranking_id ?? undefined,
                    })
                    // A first-page load for a changed query started meanwhile. Its rows win, so this
                    // page of the old query must not land on top of them.
                    if (cache.firstPageRequestId !== firstPageRequestId && values.reportsResponse) {
                        return values.reportsResponse
                    }
                    const latest = values.reportsResponse?.results ?? []
                    return {
                        ...response,
                        results: [...latest, ...keepRowFieldsWrittenDuringFetch(response.results, current, latest)],
                        // Only the first page reads the status, so a later page must not blank it.
                        personal_ranking_status: values.reportsResponse?.personal_ranking_status ?? null,
                        requestParams: params,
                        requestContext,
                    }
                },
            },
        ],
    })),

    reducers({
        unassigningReportIds: [
            [] as string[],
            {
                unassignMe: (state, { reportId }) => (state.includes(reportId) ? state : [...state, reportId]),
                unassignMeFinished: (state, { reportId }) => state.filter((id) => id !== reportId),
            },
        ],
        claimSavingReportIds: [
            [] as string[],
            {
                setReportClaimed: (state, { report }) => (state.includes(report.id) ? state : [...state, report.id]),
                setReportClaimedFinished: (state, { reportId }) => state.filter((id) => id !== reportId),
            },
        ],
        // Kept apart from `reportsResponse` so a refresh that replaces the rows does not blank the
        // source line while the lookup runs again.
        reportSourceMeta: [
            {} as Record<string, ReportSourceMeta>,
            {
                applyReportSourceMeta: (state, { meta }) => ({ ...state, ...meta }),
            },
        ],
        reportsResponse: {
            // Only the numbers change: the row keeps its title, summary, and query as loaded.
            applyReportMetricSnapshots: (state, { snapshots }) =>
                state
                    ? { ...state, results: state.results.map((r) => mergeReportMetricSnapshots(r, snapshots)) }
                    : state,
            // Optimistic removal on archive – keeps the list snappy; count refreshes in the background.
            removeReport: (state, { reportId }) =>
                state
                    ? {
                          ...state,
                          results: state.results.filter((r) => r.id !== reportId),
                          count: Math.max(0, state.count - 1),
                      }
                    : state,
            setReportAssignee: (state, { reportId, assignee }) =>
                state?.results.some((r) => r.id === reportId)
                    ? { ...state, results: state.results.map((r) => (r.id === reportId ? { ...r, assignee } : r)) }
                    : state,
            setSuggestedToMe: (state, { reportIds, isSuggested }) => {
                const ids = new Set(reportIds)
                // Keep the same state when no row changes, so an unrelated edit does not re-render the list.
                return state?.results.some((r) => ids.has(r.id) && r.is_suggested_reviewer !== isSuggested)
                    ? {
                          ...state,
                          results: state.results.map((r) =>
                              ids.has(r.id) ? { ...r, is_suggested_reviewer: isSuggested } : r
                          ),
                      }
                    : state
            },
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
        // The PostHog user the reviewer scope narrows the list to. Undefined for Entire project.
        scopeReviewerUuid: [
            (s) => [s.scope, s.user],
            (scope: InboxScope, user: UserType | null): string | undefined =>
                scope === INBOX_SCOPE_FOR_YOU ? (user?.uuid ?? undefined) : teammateUuidFromScope(scope),
        ],
        // `mine` also covers the claims of the user's agents and tasks, where `me` matches only the exact actor.
        scopeAssignee: [
            (s) => [s.scope],
            (scope: InboxScope): 'mine' | undefined => (scope === INBOX_SCOPE_CLAIMED_BY_YOU ? 'mine' : undefined),
        ],
        // The section's fixed filter merged with the user-driven chrome + reviewer scope (server-side).
        listApiParams: [
            (s) => [
                s.searchQuery,
                s.activeSortField,
                s.activeSortDirection,
                s.activeSourceProductFilter,
                s.activeScoutFilter,
                s.priorityFilter,
                s.scopeReviewerUuid,
                s.scope,
                s.scopeAssignee,
                s.activeCreatedWindow,
                (_, p) => p.listParams,
            ],
            (
                searchQuery: string,
                sortField: import('./inboxFiltersLogic').InboxSortField,
                sortDirection: import('./inboxFiltersLogic').InboxSortDirection,
                sourceProductFilter: string[],
                scoutFilter: string[],
                priorityFilter: import('../types').SignalReportPriority[],
                suggestedReviewer: string | undefined,
                scope: InboxScope,
                assignee: 'mine' | undefined,
                activeCreatedWindow: InboxCreatedWindow | null,
                listParams
            ) => {
                const teammateUuid = teammateUuidFromScope(scope)
                return {
                    ...listParams,
                    search: appliedInboxSearch(searchQuery),
                    ...buildSignalReportListSortParams(sortField, sortDirection),
                    source_product: sourceProductFilter.length > 0 ? sourceProductFilter.join(',') : undefined,
                    scout: scoutFilter.length > 0 ? scoutFilter.join(',') : undefined,
                    priority: priorityFilter.length > 0 ? priorityFilter.join(',') : undefined,
                    suggested_reviewers: suggestedReviewer,
                    // `suggested_reviewers` only filters. These make `sort=personal` read the teammate's ranking.
                    scope: teammateUuid ? 'teammate' : undefined,
                    teammate_uuid: teammateUuid,
                    assignee,
                    created_window: activeCreatedWindow ?? undefined,
                    // Rows render from Postgres alone; `loadReportSourceMeta` fills the source line after.
                    include_source_metadata: 'false',
                }
            },
        ],
        reports: [
            (s) => [s.reportsResponse, s.reportSourceMeta],
            (
                reportsResponse: ReportListResponse | null,
                reportSourceMeta: Record<string, ReportSourceMeta>
            ): SignalReport[] =>
                (reportsResponse?.results ?? []).map((report) =>
                    reportSourceMeta[report.id] ? { ...report, ...reportSourceMeta[report.id] } : report
                ),
        ],
        // Rows whose metric snapshot is missing or older than the server's freshness window. Rows
        // refreshed on an earlier page are fresh, so a next-page load only sends the new ones.
        staleMetricReportIds: [
            (s) => [s.reports],
            (reports: SignalReport[]): string[] =>
                reports.filter((report) => reportNeedsMetricRefresh(report, Date.now())).map((report) => report.id),
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
        // The loaded rows whose pull request is still in flight, so the pill can say whether CI is
        // red. A draft counts: it still builds. A merged or closed pull request is left out — its
        // checks are history, not something to act on.
        livePrReportIds: [
            (s) => [s.reports],
            (reports: SignalReport[]): string[] =>
                reports
                    .filter((report) => {
                        if (reportPullRequests(report).length === 0) {
                            return false
                        }
                        const prState = derivePrState(
                            report.status,
                            primaryReportPullRequest(report).merged === true,
                            primaryReportPullRequest(report).state
                        )
                        return prState === 'open' || prState === 'draft'
                    })
                    .map((report) => report.id),
        ],
        // Total matching the *loaded* results — from the same response, so it can never be stale
        // relative to `reports` the way the separately-loaded badge `count` can (filter/refresh races).
        totalCount: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): number | null => reportsResponse?.count ?? null,
        ],
        // A search stops counting past a cap, so `count` is a lower bound when this is true.
        countIsCapped: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean => reportsResponse?.count_is_capped === true,
        ],
        // Stable key for the query that produced the loaded response. Unlike `listApiParams`, this
        // only changes when a response fetched with the new params actually lands, so consumers
        // never associate the new query with rows from the previous one.
        loadedQueryKey: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): string | null =>
                reportsResponse?.requestParams ? JSON.stringify(reportsResponse.requestParams) : null,
        ],
        // Nothing that can still change the count is in flight, and the count on screen belongs to
        // the current query. A failed page settles the section on what it had, rather than holding
        // a consumer forever.
        countSettled: [
            (s) => [
                s.countLoading,
                s.reportsResponseLoading,
                s.reportsResponse,
                s.reportsLoadFailed,
                s.loadedQueryKey,
                s.listApiParams,
            ],
            (
                countLoading: boolean,
                reportsResponseLoading: boolean,
                reportsResponse: ReportListResponse | null,
                reportsLoadFailed: boolean,
                loadedQueryKey: string | null,
                listApiParams: any
            ): boolean =>
                !countLoading &&
                !reportsResponseLoading &&
                (reportsResponse === null || reportsLoadFailed || loadedQueryKey === JSON.stringify(listApiParams)),
        ],
        // Display context (scope, active-filters flag) as it was when the loaded response was
        // requested — for telemetry, so an in-flight response can't be labeled with context the
        // user switched to after the request went out.
        loadedContext: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): ReportListRequestContext | null =>
                reportsResponse?.requestContext ?? null,
        ],
        // The ranker the server used for a Recommended or Personalized list: `priority`, a model head or
        // `personal`. Null for other sorts.
        loadedRanker: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): string | null => reportsResponse?.ranker ?? null,
        ],
        // Whether the cards show score pills: the server put this user in a Recommended arm that shows
        // them, or the list is Personalized, which shows them to everyone.
        loadedRankingPill: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean =>
                reportsResponse?.ranking_pill === true || reportsResponse?.requestContext?.sortField === 'personal',
        ],
        // A stored personal ranking ordered the list: the Personalized sort, or the Recommended sort in the
        // arm that serves the personal order.
        loadedPersonalOrder: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean => reportsResponse?.ranker === 'personal',
        ],
        // The user's own stored personal ranking as the first page found it. Null when personal ranking is off.
        loadedPersonalRankingStatus: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): PaginatedSignalReportListListApiPersonalRankingStatus =>
                reportsResponse?.personal_ranking_status ?? null,
        ],
        // The user asked for the Personalized sort, but they have no stored personal ranking, so the
        // server answered with the Recommended order.
        loadedPersonalFallback: [
            (s) => [s.reportsResponse],
            (reportsResponse: ReportListResponse | null): boolean =>
                reportsResponse?.requestContext?.sortField === 'personal' && reportsResponse.ranker !== 'personal',
        ],
    }),

    listeners(({ actions, values, props, cache }) => ({
        loadCount: () => {
            if (props.sectionKey === 'closed' || props.sectionKey === 'outcome-monitoring') {
                actions.loadHasProjectReports()
            }
        },
        // Announce this section's open pull requests so their CI state is resolved in one batch. Both
        // loaders report: the first page and each appended page bring rows that need painting. An
        // empty announcement matters too, because it retires the rows a narrowed filter dropped.
        loadReportsSuccess: () => {
            applyDefaultScopeIfEmpty(props, values, actions)
            setInboxServedRanker(values.loadedRanker, values.loadedRankingPill)
            actions.trackReports(props.sectionKey, values.livePrReportIds)
            actions.refreshReportMetrics(values.staleMetricReportIds)
            // A first page or a refresh asks again for every row, because a report gains sources as
            // new signals land. The rows keep their previous values until the answer arrives.
            actions.loadReportSourceMeta(values.reports.map((report) => report.id))
        },
        loadMoreReportsSuccess: () => {
            actions.trackReports(props.sectionKey, values.livePrReportIds)
            actions.refreshReportMetrics(values.staleMetricReportIds)
            actions.loadReportSourceMeta(
                values.reports.map((report) => report.id).filter((id) => !(id in values.reportSourceMeta))
            )
        },
        // Skips the ids a request already in flight covers, so overlapping page loads do not repeat
        // the ClickHouse query.
        loadReportSourceMeta: async ({ reportIds }) => {
            const inFlight: Set<string> = (cache.sourceMetaInFlight ??= new Set<string>())
            const requested = reportIds.filter((id) => !inFlight.has(id))
            if (requested.length === 0) {
                return
            }
            requested.forEach((id) => inFlight.add(id))
            try {
                const response = await signalsReportsSourceMetadataCreate(String(ApiConfig.getCurrentProjectId()), {
                    report_ids: requested,
                })
                actions.applyReportSourceMeta(
                    Object.fromEntries(
                        response.reports.map(({ id, source_products, scout_name }) => [
                            id,
                            { source_products: [...source_products], scout_name },
                        ])
                    )
                )
            } catch (error) {
                posthog.captureException(error)
            } finally {
                requested.forEach((id) => inFlight.delete(id))
            }
        },
        // One page of ids per request, sent one after the other so a page open never fans out into
        // parallel query bursts. A newer page load supersedes an in-flight refresh at the breakpoint.
        refreshReportMetrics: async ({ reportIds }, breakpoint) => {
            if (!isReportMetricsEnabled(values.featureFlags)) {
                return
            }
            for (let offset = 0; offset < reportIds.length; offset += METRIC_REFRESH_PAGE_SIZE) {
                const page = reportIds.slice(offset, offset + METRIC_REFRESH_PAGE_SIZE)
                let response: Awaited<ReturnType<typeof signalsReportsRefreshMetricsCreate>>
                try {
                    response = await signalsReportsRefreshMetricsCreate(String(values.currentTeamId), {
                        report_ids: page,
                    })
                } catch {
                    return
                }
                breakpoint()
                actions.applyReportMetricSnapshots([...response.reports])
            }
        },
        loadCountSuccess: () => applyDefaultScopeIfEmpty(props, values, actions),
        ensureLoaded: () => {
            if (values.reportsResponse === null && !values.reportsResponseLoading) {
                actions.loadReports()
            }
        },
        loadMore: () => {
            // Page only from rows of the current query. Rows from before a filter change get
            // replaced, so a next page appended to them would mix two queries.
            if (
                values.hasMore &&
                !values.reportsResponseLoading &&
                values.loadedQueryKey === JSON.stringify(values.listApiParams)
            ) {
                actions.loadMoreReports()
            }
        },
        refresh: () => {
            // An in-flight first page was requested with the old filters, so it reloads too. The page
            // response carries the total, so a separate count would run the same COUNT(*) twice.
            if (values.isLoaded || values.reportsResponseLoading) {
                actions.loadReports()
                // Status option availability is project-wide, so a scoped page cannot answer it.
                // The `loadCount` listener does not run on this path.
                if (props.sectionKey === 'closed' || props.sectionKey === 'outcome-monitoring') {
                    actions.loadHasProjectReports()
                }
            } else {
                actions.loadCount()
            }
        },
        // User-driven filter/scope changes re-fetch the rows if this section is loaded, and only the count if not.
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.refresh()
        },
        setSort: () => actions.refresh(),
        resetUnavailableSort: () => actions.refresh(),
        setCreatedWindow: () => actions.refresh(),
        applyDefaultCreatedWindow: () => actions.refresh(),
        toggleSourceProduct: () => actions.refresh(),
        toggleScout: () => actions.refresh(),
        setSourceFilter: () => actions.refresh(),
        sourceFilterAvailabilityChanged: () => actions.refresh(),
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
                await setReportState(reportId, {
                    state: 'suppressed',
                    ...suppressDismissalPayload(dismissal),
                })
                // Reconcile every mounted section against the server so the Dismissed target gains the
                // row and count, not just this source section (which already dropped it optimistically).
                inboxBulkActionsLogic.actions.reportStateChanged()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to dismiss report')
                reloadAfterFailedWrite(reportId, actions.refresh)
            }
        },
        // Mark a report done without an inbox PR (transition to `resolved`). Optimistically drops it
        // from this section; the broadcast below reconciles every section, so it joins Resolved now.
        resolveReport: async ({ reportId, reason, note }) => {
            actions.removeReport(reportId)
            try {
                await setReportState(reportId, {
                    state: 'resolved',
                    dismissal_reason: reason,
                    ...(note ? { dismissal_note: note } : {}),
                })
                lemonToast.success('Report resolved')
                // Reconcile every mounted section so the Resolved target gains the row and count.
                inboxBulkActionsLogic.actions.reportStateChanged()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to resolve report')
                reloadAfterFailedWrite(reportId, actions.refresh)
            }
        },
        // Restore a suppressed report back to the inbox (transition to `potential`). Optimistically
        // drops it from Dismissed; the report re-enters the pipeline and resurfaces elsewhere.
        restoreReport: async ({ reportId, surface }) => {
            const report = values.reports.find((r) => r.id === reportId)
            actions.removeReport(reportId)
            try {
                await setReportState(reportId, { state: 'potential' })
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
                reloadAfterFailedWrite(reportId, actions.refresh)
            }
        },
        // A bulk dismiss or resolve happens in the singleton; refresh this section once it lands so
        // the affected reports leave it and the counts settle.
        [inboxBulkActionsLogic.actionTypes.bulkDismissSuccess]: () => actions.refresh(),
        [inboxBulkActionsLogic.actionTypes.bulkResolveSuccess]: () => actions.refresh(),
        // A bulk claim reloads after a failure too, because the server can save some claims before it fails.
        [inboxBulkActionsLogic.actionTypes.bulkClaimSuccess]: () => actions.refresh(),
        [inboxBulkActionsLogic.actionTypes.bulkClaimFailure]: () => actions.refresh(),
        // A single report dismissed, resolved, or refunded elsewhere (e.g. the detail pane) – reconcile
        // this section against the server so the report leaves its section and joins Resolved or
        // Dismissed, counts included.
        [inboxBulkActionsLogic.actionTypes.reportStateChanged]: () => actions.refresh(),
        [inboxBulkActionsLogic.actionTypes.reportWriteFailed]: () => actions.refresh(),
        // A reviewer edit can take a report out of this list's reviewer scope. Drop the row in place
        // rather than refetch: a refetch reloads only the first page, which loses the scroll position.
        [inboxBulkActionsLogic.actionTypes.reportReviewersChanged]: ({ reportId, reviewerUuids }) => {
            const scopeUuid = values.scopeReviewerUuid
            if (scopeUuid && !reviewerUuids.includes(scopeUuid) && values.reports.some((r) => r.id === reportId)) {
                actions.removeReport(reportId)
                return
            }
            // Triage and the bulk bar offer Unassign me from this flag, so it follows the edit too.
            const userUuid = values.user?.uuid
            if (userUuid) {
                actions.setSuggestedToMe([reportId], reviewerUuids.includes(userUuid))
            }
        },
        // The Claimed by you list holds only the user's claims: a release drops the row in place, and a
        // new claim reloads the list so the row joins it. Every other list updates the claim tag.
        [inboxBulkActionsLogic.actionTypes.reportClaimChanged]: ({ reportId, assignee }) => {
            const isLoaded = values.reports.some((r) => r.id === reportId)
            if (values.scopeAssignee) {
                const isMine = !!values.user?.uuid && assignee?.responsible_user?.uuid === values.user.uuid
                if (!isMine && isLoaded) {
                    actions.removeReport(reportId)
                    return
                }
                if (isMine && !isLoaded) {
                    actions.refresh()
                    return
                }
            }
            actions.setReportAssignee(reportId, assignee)
        },
        [inboxBulkActionsLogic.actionTypes.unassignedMe]: ({ reportIds }: { reportIds: string[] }) => {
            if (values.isScopedToMe) {
                const loadedIds = new Set(values.reportsResponse?.results.map((r) => r.id))
                reportIds.filter((id) => loadedIds.has(id)).forEach((id) => actions.removeReport(id))
            } else {
                actions.setSuggestedToMe(reportIds, false)
            }
        },
        unassignMe: async ({ reportId, surface, reason }) => {
            const report = values.reports.find((r) => r.id === reportId)
            captureInboxReportAction({
                report,
                actionType: 'remove_suggested_reviewer',
                surface,
                // pinned: analytics property names — renaming breaks dashboards
                extra: reason ? { removal_reason: reason } : undefined,
            })
            const teamId = String(values.currentTeamId)
            try {
                await (reason
                    ? signalsReportsReviewersMeCreate(teamId, reportId, { removal_reason: reason })
                    : signalsReportsReviewersMeDestroy(teamId, reportId))
            } catch (error: any) {
                lemonToast.error(error?.detail || "Couldn't unassign you from the report. Try again.")
                return
            } finally {
                actions.unassignMeFinished(reportId)
            }
            lemonToast.success('Unassigned you from the report')
            // The list that started the request can unmount while it runs, for example when triage closes.
            inboxBulkActionsLogic.findMounted()?.actions.unassignedMe([reportId])
        },
        setReportClaimed: async ({ report, claimed, surface, takeover }) => {
            captureInboxReportAction({
                report,
                actionType: claimed ? 'claim' : 'unclaim',
                surface,
                extra: takeover ? { takeover: true } : undefined,
            })
            const outcome = await requestReportClaim(String(values.currentTeamId), report, claimed, {
                currentUserUuid: values.user?.uuid ?? null,
                takeover,
            })
            actions.setReportClaimedFinished(report.id)
            if (!outcome.ok) {
                lemonToast.error(outcome.message)
                // Reload so the row shows who holds the claim now. A request that failed without an answer
                // may still have saved the claim.
                reloadAfterFailedWrite(report.id, actions.refresh)
                return
            }
            // Every mounted list updates the row, and the Claimed by you list gains or drops it.
            const bulkActions = inboxBulkActionsLogic.findMounted()
            if (bulkActions) {
                bulkActions.actions.reportClaimChanged(report.id, outcome.updated.assignee)
            } else {
                actions.setReportAssignee(report.id, outcome.updated.assignee)
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCount()
        },
    })),
])
