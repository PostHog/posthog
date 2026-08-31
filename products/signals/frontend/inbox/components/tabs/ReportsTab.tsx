import { useMountedLogic, useValues } from 'kea'
import { JSX, useCallback, useEffect, useRef } from 'react'

import { IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { captureInboxViewed } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxFiltersLogic, isDefaultStateFilter } from '../../logics/inboxFiltersLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import {
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
} from '../../types'
import { mergeReportRows, selectedFlatListSections } from '../../utils/flatReportList'
import { CardSkeleton } from '../cards/CardSkeleton'
import { ReportCard } from '../cards/ReportCard'
import { ReportContextMenu } from '../cards/ReportContextMenu'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'
import { InboxBulkSelectionBar } from '../shell/InboxBulkSelectionBar'
import { InboxReportFilters } from '../shell/InboxReportFilters'
import { InboxScopeFilter } from '../shell/InboxScopeFilter'
import { useReportImpressions } from '../useReportImpressions'

/**
 * The states that make up "the inbox" for the `Inbox viewed` event. Not actionable is left out: it
 * is a staff triage surface, and counting it would report a non-empty inbox on a project that has
 * surfaced nothing worth acting on. The empty-state verdict is a separate question, answered over
 * the states the current user can actually see.
 */
const COUNTED_SECTION_KEYS = ['needs-decision', 'monitoring', 'resolved', 'dismissed'] as const

type CountedSectionKey = (typeof COUNTED_SECTION_KEYS)[number]

interface SectionListState {
    count: number | null
    countLoading: boolean
    reports: SignalReport[]
    isLoaded: boolean
    reportsLoadFailed: boolean
    pageLoadFailed: boolean
    reportsResponseLoading: boolean
    hasMore: boolean
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
        reports,
        isLoaded,
        reportsLoadFailed,
        pageLoadFailed,
        reportsResponseLoading,
        hasMore,
    } = useValues(reportListLogic(sectionListLogicProps(sectionKey)))
    return {
        count,
        countLoading,
        reports,
        isLoaded,
        reportsLoadFailed,
        pageLoadFailed,
        reportsResponseLoading,
        hasMore,
    }
}

/**
 * Every state's count and loaded rows, keyed by state. All five logics are mounted regardless of
 * who is looking or which states the filter selects, so the hooks never change shape when the
 * staff flag resolves or a checkbox toggles; callers decide which states matter to them.
 */
function useSectionStates(): Record<InboxReportSectionKey, SectionListState> {
    return {
        monitoring: useSectionState('monitoring'),
        'needs-decision': useSectionState('needs-decision'),
        resolved: useSectionState('resolved'),
        dismissed: useSectionState('dismissed'),
        'not-actionable': useSectionState('not-actionable'),
    }
}

/**
 * `Inbox viewed`, fired once per Reports mount as soon as every counted state's count has settled.
 * One event per visit, carrying the whole loaded list.
 */
function useInboxViewedEvent(sections: Record<CountedSectionKey, SectionListState>): void {
    const { hasActiveFilters, sourceProductFilter, priorityFilter, visibleStateFilter, scope } =
        useValues(inboxFiltersLogic)
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

    // A count is settled once its request is no longer in flight: loaded, refreshed, or failed
    // (count stays null). Waiting on the loading flags rather than non-null values means a scope or
    // filter refresh in progress doesn't fire the event with the previous query's counts.
    const settled = COUNTED_SECTION_KEYS.every((key) => !sections[key].countLoading)
    const firedRef = useRef(false)

    useEffect(() => {
        if (!listVisible || !settled || firedRef.current) {
            return
        }
        firedRef.current = true
        captureInboxViewed({
            // pinned: analytics property. `tab` names the inbox page tab; dashboards group on it.
            tab: 'reports',
            reports: COUNTED_SECTION_KEYS.flatMap((key) => sections[key].reports),
            totalCount: COUNTED_SECTION_KEYS.reduce((sum, key) => sum + (sections[key].count ?? 0), 0),
            pullsTabCount: sections.monitoring.count,
            reportsTabCount: sections['needs-decision'].count,
            hasActiveFilters,
            sourceProductFilter,
            priorityFilter,
            stateFilter: visibleStateFilter,
            scope,
        })
    }, [
        listVisible,
        settled,
        sections,
        hasActiveFilters,
        sourceProductFilter,
        priorityFilter,
        visibleStateFilter,
        scope,
    ])
}

/** Nothing has reached the inbox yet — the whole list is empty, not just one state. */
function ReportsEmptyState(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    if (featureFlags[FEATURE_FLAGS.INBOX_SELF_DRIVING_EMPTY_STATE] === 'empty-state') {
        return <InboxWaitingForWork />
    }
    return (
        <div className="mx-auto flex max-w-md flex-col items-center gap-2 py-12 text-center">
            <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-fill-primary text-secondary">
                <IconNotebook className="text-2xl" />
            </div>
            <h3 className="m-0 text-base font-semibold">Nothing in your inbox yet</h3>
            <p className="m-0 text-sm text-tertiary">
                Agents file what they find here: reports waiting on a pull request, pull requests for you to review, and
                the work already resolved.
            </p>
            <SelfDrivingInstallingHint>
                Reports will start arriving as soon as live data comes in.
            </SelfDrivingInstallingHint>
        </div>
    )
}

function emptyListCopy(scope: InboxScope, narrowed: boolean): string {
    if (narrowed) {
        return 'No reports match the current filters.'
    }
    if (scope === INBOX_SCOPE_FOR_YOU) {
        return 'No reports suggested for you yet. Switch the scope to see the entire project.'
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
    const { isStaff } = useValues(inboxSceneLogic)
    // The row context menus dispatch to this logic and unmount when a menu closes; pinning it here
    // keeps an in-flight create-PR listener alive past the click that closed the menu.
    useMountedLogic(inboxTaskKickoffLogic)
    const { hasActiveFilters, visibleStateFilter, scope, sortField, sortDirection } = useValues(inboxFiltersLogic)
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
    const rows = mergeReportRows(reportsBySection, selectedSections, sortField, sortDirection)
    useReportImpressions(rows, selectedSections)

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
    const anyLoadFailed = selectedSections.some((key) => sections[key].reportsLoadFailed && !sections[key].isLoaded)
    const pageLoading = selectedSections.some((key) => sections[key].reportsResponseLoading)
    const pageLoadFailed = selectedSections.some((key) => sections[key].pageLoadFailed)
    const hasMore = selectedSections.some((key) => sections[key].hasMore)

    // `ensureLoaded` only fetches a state with nothing loaded and nothing in flight, so retrying
    // after a partial failure refetches the failed states and leaves the loaded ones alone.
    const retryFailedSections = (): void => {
        selectedSections.forEach((key) => reportListLogic(sectionListLogicProps(key)).actions.ensureLoaded())
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

    return (
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-6 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <InboxReportFilters />
                <div className="ml-auto flex shrink-0 items-center gap-2">
                    <LemonButton
                        type="primary"
                        size="small"
                        to={urls.inboxTriage()}
                        sideIcon={<KeyboardShortcut t />}
                        tooltip="Go through the reports that need a pull request one at a time"
                        data-attr="inbox-triage-mode"
                    >
                        Triage mode
                    </LemonButton>
                    <InboxScopeFilter />
                </div>
            </div>
            <InboxBulkSelectionBar />

            {inboxIsEmpty ? (
                <ReportsEmptyState />
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
                    {rows.map(({ report, sectionKey }) => (
                        <ReportContextMenu key={report.id} report={report} sectionKey={sectionKey}>
                            <ReportCard
                                report={report}
                                sectionKey={sectionKey}
                                onRestore={() =>
                                    reportListLogic(sectionListLogicProps(sectionKey)).actions.restoreReport(
                                        report.id,
                                        'list_row'
                                    )
                                }
                            />
                        </ReportContextMenu>
                    ))}
                    {/* Skeleton cards continue the list while the next pages load – sleeker than a spinner. */}
                    {pageLoading && <CardSkeleton count={2} variant="cards" dashed />}
                    {anyLoadFailed && (
                        <div className="flex items-center gap-2 px-1 py-2">
                            <p className="m-0 text-sm text-tertiary">Couldn't load some of the reports.</p>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
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
