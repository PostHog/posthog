import { useMountedLogic, useValues } from 'kea'
import { Fragment, JSX, memo, useCallback, useEffect, useRef } from 'react'

import { LemonBanner, LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { PaginatedSignalReportListListApiPersonalRankingStatus } from '../../../generated/api.schemas'
import { isMergeKeySortField, isRankingSortField } from '../../filterOptions'
import { captureInboxViewed } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxActivationVisibilityLogic } from '../../logics/inboxActivationVisibilityLogic'
import { inboxFiltersLogic, isDefaultStateFilter } from '../../logics/inboxFiltersLogic'
import type { InboxRankingSortField } from '../../logics/inboxFiltersLogic'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { ReportListRequestContext, reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import {
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_CLAIMED_BY_YOU,
    INBOX_SCOPE_FOR_YOU,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
} from '../../types'
import { mergeReportRows, selectedFlatListSections } from '../../utils/flatReportList'
import { rankingSortScore } from '../../utils/reportOrdering'
import { CardSkeleton } from '../cards/CardSkeleton'
import { ReportCard } from '../cards/ReportCard'
import { ReportContextMenu } from '../cards/ReportContextMenu'
import { FirstReportProgress } from '../emptyState/FirstReportProgress'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { InboxMcpBanner } from '../InboxMcpBanner'
import { InboxActivationPanel } from '../onboarding/InboxActivationPanel'
import { InboxBulkSelectionBar } from '../shell/InboxBulkSelectionBar'
import { InboxFiltersPanel } from '../shell/InboxFiltersPanel'
import { InboxReportFilters } from '../shell/InboxReportFilters'
import { InboxScopeFilter } from '../shell/InboxScopeFilter'
import { InboxSortSelect } from '../shell/InboxSortSelect'
import { useReportImpressions } from '../useReportImpressions'
import { useSelectableReportList } from '../useSelectableReportList'
import { QuillReportsList, QuillReportsListState } from './QuillReportsList'

/**
 * The states that make up "the inbox" for the `Inbox viewed` event. Not actionable is left out: it
 * is a staff triage surface, and counting it would report a non-empty inbox on a project that has
 * surfaced nothing worth acting on. The empty-state verdict is a separate question, answered over
 * the states the current user can actually see.
 */
const COUNTED_SECTION_KEYS = ['needs-decision', 'monitoring', 'resolved', 'closed', 'dismissed', 'held-back'] as const

type CountedSectionKey = (typeof COUNTED_SECTION_KEYS)[number]

interface SectionListState {
    count: number | null
    countLoading: boolean
    countSettled: boolean
    reports: SignalReport[]
    isLoaded: boolean
    reportsLoadFailed: boolean
    pageLoadFailed: boolean
    reportsResponseLoading: boolean
    hasMore: boolean
    loadedRankingPill: boolean
    loadedPersonalOrder: boolean
    loadedPersonalFallback: boolean
    loadedPersonalRankingStatus: PaginatedSignalReportListListApiPersonalRankingStatus
    loadedContext: ReportListRequestContext | null
    loadedRanker: string | null
}

/**
 * Read one value at a time rather than spreading what `useValues` returns: it hands back a proxy
 * whose properties are subscribing getters, and spreading it yields an empty object — silently, and
 * with a type that still claims every value is there.
 */
function useSectionState(sectionKey: InboxReportSectionKey): SectionListState {
    const {
        count,
        countLoading,
        countSettled,
        reports,
        isLoaded,
        reportsLoadFailed,
        pageLoadFailed,
        reportsResponseLoading,
        hasMore,
        loadedRankingPill,
        loadedPersonalOrder,
        loadedPersonalFallback,
        loadedPersonalRankingStatus,
        loadedContext,
        loadedRanker,
    } = useValues(reportListLogic(sectionListLogicProps(sectionKey)))
    return {
        count,
        countLoading,
        countSettled,
        reports,
        isLoaded,
        reportsLoadFailed,
        pageLoadFailed,
        reportsResponseLoading,
        hasMore,
        loadedRankingPill,
        loadedPersonalOrder,
        loadedPersonalFallback,
        loadedPersonalRankingStatus,
        loadedContext,
        loadedRanker,
    }
}

/**
 * Every state's count and loaded rows, keyed by state. All logics are mounted regardless of
 * who is looking or which states the filter selects, so the hooks never change shape when the
 * staff flag resolves or a checkbox toggles; callers decide which states matter to them.
 */
function useSectionStates(): Record<InboxReportSectionKey, SectionListState> {
    return {
        monitoring: useSectionState('monitoring'),
        'needs-decision': useSectionState('needs-decision'),
        'outcome-monitoring': useSectionState('outcome-monitoring'),
        resolved: useSectionState('resolved'),
        closed: useSectionState('closed'),
        dismissed: useSectionState('dismissed'),
        'held-back': useSectionState('held-back'),
        'not-actionable': useSectionState('not-actionable'),
    }
}

/**
 * `Inbox viewed`, fired once per Reports mount as soon as every counted state's count has settled.
 * One event per visit, carrying the whole loaded list.
 */
function useInboxViewedEvent(sections: Record<CountedSectionKey, SectionListState>): void {
    const {
        hasActiveFilters,
        activeSourceProductFilter,
        priorityFilter,
        visibleStateFilter,
        scope,
        isScopedToMe,
        activeSortField,
    } = useValues(inboxFiltersLogic)
    // The list stays mounted (hidden) while a report/scout detail is open, so gate the view event on
    // the list actually being the visible surface — otherwise a deep-link to a report fires a phantom
    // `Inbox viewed` and then suppresses the real one when the user navigates back to the list.
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen, isRunsOpen, isTriageOpen } =
        useValues(inboxSceneLogic)
    const listVisible =
        !selectedReportId &&
        !selectedScoutSkillName &&
        !isScratchpadOpen &&
        !isFindingsOpen &&
        !isRunsOpen &&
        !isTriageOpen

    // Waiting on `countSettled` rather than the loading flags means a scope or filter change
    // doesn't fire the event with the previous query's counts.
    const settled = COUNTED_SECTION_KEYS.every((key) => sections[key].countSettled)
    const firedRef = useRef(false)

    useEffect(() => {
        if (!listVisible || !settled || firedRef.current) {
            return
        }
        firedRef.current = true
        const totalCount = COUNTED_SECTION_KEYS.reduce((sum, key) => sum + (sections[key].count ?? 0), 0)
        // Every first page carries the same status, sort and ranker, so the first loaded state stands for the list.
        const served = COUNTED_SECTION_KEYS.map((key) => sections[key]).find((section) => section.isLoaded)
        captureInboxViewed({
            // pinned: analytics property. `tab` names the inbox page tab; dashboards group on it.
            tab: 'reports',
            reports: COUNTED_SECTION_KEYS.flatMap((key) => sections[key].reports),
            totalCount,
            pullsTabCount: sections.monitoring.count,
            reportsTabCount: sections['needs-decision'].count,
            hasActiveFilters,
            sourceProductFilter: activeSourceProductFilter,
            priorityFilter,
            stateFilter: visibleStateFilter,
            scope,
            personalRankingStatus: served?.loadedPersonalRankingStatus ?? null,
            // The counts cover every counted state, so they are the For you count when nothing else narrows them.
            forYouReportCount: isScopedToMe && !hasActiveFilters ? totalCount : null,
            sortField: served?.loadedContext?.sortField ?? activeSortField,
            rankerId: served?.loadedRanker ?? null,
        })
    }, [
        listVisible,
        settled,
        sections,
        hasActiveFilters,
        activeSourceProductFilter,
        priorityFilter,
        visibleStateFilter,
        scope,
        isScopedToMe,
        activeSortField,
    ])
}

/**
 * One row of the flat list, memoized. The list above it re-renders on every count, page and poll
 * that lands, and repainting a few hundred rows each time is what made the inbox stop answering
 * clicks. The restore closure is built here so the row's props stay comparable.
 */
const ReportRow = memo(function ReportRow({
    report,
    sectionKey,
    rankingSortField,
    rankingPill,
    personalSort,
    timestampField,
    hideOwnClaim,
}: {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    rankingSortField: InboxRankingSortField | null
    rankingPill: boolean
    personalSort: boolean
    timestampField: 'created_at' | 'updated_at'
    hideOwnClaim: boolean
}): JSX.Element {
    return (
        <ReportContextMenu report={report} sectionKey={sectionKey}>
            <ReportCard
                report={report}
                selectable
                rankingSortField={rankingSortField}
                rankingPill={rankingPill}
                personalSort={personalSort}
                timestampField={timestampField}
                hideOwnClaim={hideOwnClaim}
                onRestore={() =>
                    reportListLogic(sectionListLogicProps(sectionKey)).actions.restoreReport(report.id, 'list_row')
                }
            />
        </ReportContextMenu>
    )
})

function quillListState({
    inboxIsEmpty,
    loading,
    hasRows,
    failed,
}: {
    inboxIsEmpty: boolean
    loading: boolean
    hasRows: boolean
    failed: boolean
}): QuillReportsListState {
    if (inboxIsEmpty) {
        return 'empty-inbox'
    }
    if (loading) {
        return 'loading'
    }
    if (hasRows) {
        return 'rows'
    }
    return failed ? 'failed' : 'no-match'
}

function emptyListCopy(scope: InboxScope, narrowed: boolean): string {
    if (narrowed) {
        return 'No reports match the current filters.'
    }
    if (scope === INBOX_SCOPE_FOR_YOU) {
        return 'No reports suggested for you yet. Switch the scope to see the entire project.'
    }
    if (scope === INBOX_SCOPE_CLAIMED_BY_YOU) {
        return "You haven't claimed any reports. Open a report and select I'm on it to claim it."
    }
    return 'No reports here yet.'
}

/**
 * The Reports tab: one toolbar over a single flat list of report cards. Each report state (Needs a
 * PR / Review and merge / Resolved / Dismissed, plus Not actionable for staff) is its own filtered
 * request via the keyed `reportListLogic`; the list merges the selected states' rows, and the
 * toolbar's state filter picks which ones those are. The toolbar, reviewer scope, and bulk
 * selection are shared across all of them.
 */
export function ReportsTab(): JSX.Element {
    const { showActivationPanel: showActivation } = useValues(inboxActivationVisibilityLogic)
    const { savedState, firstReportProgress } = useValues(inboxSetupLogic)
    const { isStaff } = useValues(inboxSceneLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    // The row context menus dispatch to this logic and unmount when a menu closes; pinning it here
    // keeps an in-flight create-PR listener alive past the click that closed the menu.
    useMountedLogic(inboxTaskKickoffLogic)
    const { hasActiveFilters, visibleStateFilter, scope, activeSortField, activeSortDirection } =
        useValues(inboxFiltersLogic)
    const rankingSortField = isRankingSortField(activeSortField) ? activeSortField : null
    const timestampField = activeSortField === 'created_at' ? 'created_at' : 'updated_at'
    const sections = useSectionStates()
    useInboxViewedEvent(sections)

    const visibleSections = selectedFlatListSections([], isStaff)
    // The state filter narrows which states' rows the list shows; an empty selection means all of
    // them. `visibleStateFilter` already drops states the user cannot see (a staff-only state from
    // a shared link or persisted storage), so a hidden state can never leave this empty and a
    // non-staff user who opens a `state=not-actionable` link still sees the full list.
    const selectedSections = selectedFlatListSections(visibleStateFilter, isStaff)

    // "Nothing yet" is a claim about the whole project, so it only holds with no filters and the
    // project-wide scope. The state selection does not gate it: counts load for every state the
    // user can see (staff still reach Not actionable when it is the only state with reports), so
    // the verdict stays true whatever states are selected. Hold the list until every count has
    // answered, so a slow first load never flashes the "nothing yet" screen at a full inbox.
    // For the empty-list copy, the state selection only counts as narrowing when the user moved it
    // off the default and it hides at least one state; the default view keeps the scope-aware copy.
    const narrowed =
        hasActiveFilters ||
        (!isDefaultStateFilter(visibleStateFilter) && selectedSections.length < visibleSections.length)
    const unfilteredView = !hasActiveFilters && scope === INBOX_SCOPE_ENTIRE_PROJECT
    const countsSettled = visibleSections.every((key) => sections[key].count !== null)
    const inboxIsEmpty = unfilteredView && countsSettled && visibleSections.every((key) => sections[key].count === 0)

    const reportsBySection = Object.fromEntries(visibleSections.map((key) => [key, sections[key].reports])) as Record<
        InboxReportSectionKey,
        SignalReport[]
    >
    const rows = mergeReportRows(reportsBySection, selectedSections, activeSortField, activeSortDirection)
    // Every state's request comes from one flag arm, so any loaded response can say whether to show pills.
    const rankingPill =
        isMergeKeySortField(activeSortField) && selectedSections.some((key) => sections[key].loadedRankingPill)
    const personalSort = activeSortField === 'personal'
    // The Recommended sort shows the personal order to the users of one flag arm.
    const personalOrder =
        personalSort ||
        (isMergeKeySortField(activeSortField) && selectedSections.some((key) => sections[key].loadedPersonalOrder))
    // Every state reads the same stored ranking, so one fallback response means the whole list fell back.
    const personalFallback = personalSort && selectedSections.some((key) => sections[key].loadedPersonalFallback)
    // Under a model sort the unscored rows trail the scored ones. A divider marks where they start.
    const firstUnscoredIndex = rankingSortField
        ? rows.findIndex(({ report }) => rankingSortScore(report, rankingSortField) === null)
        : -1
    useReportImpressions(rows, selectedSections)
    // Multi-select ranges over this order, and drops any id the merged list no longer holds.
    useSelectableReportList(rows.map(({ report }) => report.id))

    // Rows are fetched once a state is part of the rendered list — a deselected state costs one
    // count request only. `ensureLoaded` no-ops on states that already loaded or are in flight.
    const selectedSectionsKey = selectedSections.join(',')
    useEffect(() => {
        for (const key of selectedSectionsKey.split(',')) {
            if (key) {
                reportListLogic(sectionListLogicProps(key as InboxReportSectionKey)).actions.ensureLoaded()
            }
        }
    }, [selectedSectionsKey])

    const firstLoadPending = selectedSections.some((key) => !sections[key].isLoaded && !sections[key].reportsLoadFailed)
    // Selecting an unloaded state flips `firstLoadPending` back on. Rows already on screen must not
    // be replaced with a skeleton then, so the skeleton only shows before the first settle or when
    // the current selection has no rows to keep visible.
    const settledOnceRef = useRef(false)
    if (!firstLoadPending) {
        settledOnceRef.current = true
    }
    const showFirstLoadSkeleton = firstLoadPending && (!settledOnceRef.current || rows.length === 0)
    const anyLoadFailed = selectedSections.some((key) => sections[key].reportsLoadFailed)
    const pageLoading = selectedSections.some((key) => sections[key].reportsResponseLoading)
    const pageLoadFailed = selectedSections.some((key) => sections[key].pageLoadFailed)
    const hasMore = selectedSections.some((key) => sections[key].hasMore)

    const retryFailedSections = (): void => {
        selectedSections.forEach((key) => {
            if (sections[key].reportsLoadFailed && !sections[key].reportsResponseLoading) {
                const { actions } = reportListLogic(sectionListLogicProps(key))
                actions.loadCount()
                actions.loadReports()
            }
        })
    }
    // `loadMore` self-guards on `hasMore` and in-flight requests, so this only refetches the pages
    // that actually failed.
    const retryFailedPages = (): void => {
        selectedSections.forEach((key) => {
            if (sections[key].pageLoadFailed) {
                reportListLogic(sectionListLogicProps(key)).actions.loadMore()
            }
        })
    }

    // Read fresh state at intersection time via refs so the observer isn't rebuilt twice per page
    // fetch (`hasMore`/`pageLoading` both flip during a load).
    const hasMoreRef = useRef(hasMore)
    hasMoreRef.current = hasMore
    const loadingRef = useRef(pageLoading)
    loadingRef.current = pageLoading
    const selectedSectionsRef = useRef(selectedSections)
    selectedSectionsRef.current = selectedSections

    // A callback ref, not an effect: the sentinel only enters the DOM once a first page has landed
    // and `hasMore` is true, which is after a mount-only effect has already run and found nothing to
    // observe. Attaching as the node mounts is what keeps paging alive.
    const observerRef = useRef<IntersectionObserver | null>(null)
    const sentinelRef = useCallback((el: HTMLDivElement | null) => {
        observerRef.current?.disconnect()
        observerRef.current = null
        if (!el) {
            return
        }
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0]?.isIntersecting && hasMoreRef.current && !loadingRef.current) {
                    // `loadMore` self-guards, so only the states that still have pages fetch one.
                    // Paging every selected state together keeps the merged order correct: a state
                    // whose page is exhausted can't hold rows back while another runs ahead.
                    selectedSectionsRef.current.forEach((key) =>
                        reportListLogic(sectionListLogicProps(key)).actions.loadMore()
                    )
                }
            },
            // Generous prefetch margin so the next page lands well before the user reaches the bottom.
            { rootMargin: '1500px' }
        )
        observer.observe(el)
        observerRef.current = observer
    }, [])
    useEffect(() => () => observerRef.current?.disconnect(), [])

    const listBanners = (
        <>
            <InboxMcpBanner />
            {showActivation && <InboxActivationPanel hasReports={!inboxIsEmpty && rows.length > 0} />}
            {showActivation && firstReportProgress && !firstLoadPending && rows.length === 0 && (
                <div className="min-w-0" data-attr="inbox-first-report-progress">
                    <FirstReportProgress
                        result={firstReportProgress}
                        notificationEmail={savedState?.first_report_notification_email}
                    />
                </div>
            )}

            {personalFallback && !inboxIsEmpty && (
                <LemonBanner type="info">
                    Your personalized list isn't ready yet, so this is the Recommended order.
                </LemonBanner>
            )}
        </>
    )

    if (todayRailNav) {
        return (
            <QuillReportsList
                state={quillListState({
                    inboxIsEmpty: inboxIsEmpty && !anyLoadFailed,
                    loading: showFirstLoadSkeleton,
                    hasRows: rows.length > 0,
                    failed: anyLoadFailed,
                })}
                rows={rows}
                totalCount={selectedSections.reduce((sum, key) => sum + (sections[key].count ?? 0), 0)}
                timestampField={timestampField}
                emptyCopy={emptyListCopy(scope, narrowed)}
                emptyInbox={showActivation ? null : <InboxWaitingForWork />}
                banners={listBanners}
                pageLoading={pageLoading}
                someLoadFailed={anyLoadFailed}
                pageLoadFailed={pageLoadFailed}
                hasMore={hasMore}
                sentinelRef={sentinelRef}
                onRetry={retryFailedSections}
                onRetryPage={retryFailedPages}
            />
        )
    }

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-3">
            {/* When the row runs out of room it wraps at the divider: filters on one line, sort and
                scope on the next. The divider sits in the gap left of the sort group, so on a wrapped
                line it falls outside the clipped edge instead of leading the line. The sort group
                grows so scope always ends the row. */}
            <div className="@container -mx-1 overflow-x-clip px-1">
                <div className="flex items-center gap-2 @2xl:hidden">
                    <InboxFiltersPanel />
                    <InboxSortSelect />
                    <div className="ml-auto min-w-0">
                        <InboxScopeFilter />
                    </div>
                </div>
                <div className="hidden flex-wrap items-center gap-2 @2xl:flex">
                    <InboxReportFilters />
                    <div className="relative flex flex-1 items-center gap-2">
                        <LemonDivider vertical className="absolute inset-y-1 -left-[5px] m-0" />
                        <InboxSortSelect />
                        <div className="ml-auto shrink-0">
                            <InboxScopeFilter />
                        </div>
                    </div>
                </div>
            </div>
            <InboxBulkSelectionBar reports={rows.map(({ report }) => report)} />
            {listBanners}

            {inboxIsEmpty && !anyLoadFailed ? (
                showActivation ? null : (
                    <InboxWaitingForWork />
                )
            ) : showFirstLoadSkeleton ? (
                // Hold the rows until every selected state's first page has settled: the states
                // load in parallel, and painting the fastest one first would let the slower ones
                // insert rows among cards already on screen. A state selected later merges its
                // rows in when they land, with the trailing page skeleton covering the wait.
                <CardSkeleton count={4} variant="cards" dashed />
            ) : rows.length === 0 ? (
                anyLoadFailed ? (
                    <div className="flex flex-col items-start gap-2 px-1 py-2">
                        <p className="m-0 text-sm text-tertiary">Couldn't load these reports.</p>
                        <LemonButton
                            size="small"
                            type="secondary"
                            loading={pageLoading}
                            onClick={retryFailedSections}
                            data-attr="inbox-report-list-retry"
                        >
                            Retry
                        </LemonButton>
                    </div>
                ) : (
                    <p className="px-1 py-2 text-sm text-tertiary">{emptyListCopy(scope, narrowed)}</p>
                )
            ) : (
                <div className="@container flex flex-col gap-1.5">
                    {rows.map(({ report, sectionKey }, index) => (
                        <Fragment key={report.id}>
                            {index > 0 && index === firstUnscoredIndex && (
                                <LemonDivider label="Not scored yet" className="my-2 text-xs text-tertiary" />
                            )}
                            <ReportRow
                                report={report}
                                sectionKey={sectionKey}
                                rankingSortField={rankingSortField}
                                rankingPill={rankingPill}
                                personalSort={personalOrder}
                                timestampField={timestampField}
                                hideOwnClaim={scope === INBOX_SCOPE_CLAIMED_BY_YOU}
                            />
                        </Fragment>
                    ))}
                    {/* Skeleton cards continue the list while the next pages load – sleeker than a spinner. */}
                    {pageLoading && <CardSkeleton count={2} variant="cards" dashed />}
                    {anyLoadFailed && (
                        <div className="flex items-center gap-2 px-1 py-2">
                            <p className="m-0 text-sm text-tertiary">Couldn't load some of the reports.</p>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                loading={pageLoading}
                                onClick={retryFailedSections}
                                data-attr="inbox-report-list-retry"
                            >
                                Retry
                            </LemonButton>
                        </div>
                    )}
                    {/* A failed next page keeps the loaded rows and the sentinel may sit inside the
                        viewport without re-firing, so offer an explicit way to fetch it again. */}
                    {!pageLoading && pageLoadFailed && (
                        <div className="flex items-center gap-2 px-1 py-2">
                            <p className="m-0 text-sm text-tertiary">Couldn't load more reports.</p>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={retryFailedPages}
                                data-attr="inbox-report-list-retry-page"
                            >
                                Retry
                            </LemonButton>
                        </div>
                    )}
                    {hasMore && <div ref={sentinelRef} className="h-1" aria-hidden />}
                </div>
            )}
        </div>
    )
}
