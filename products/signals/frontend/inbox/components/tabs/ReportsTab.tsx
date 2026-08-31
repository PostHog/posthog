import { useActions, useValues } from 'kea'
import { JSX, useCallback, useEffect, useRef } from 'react'

import { IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { captureInboxViewed } from '../../inboxAnalytics'
import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import type { InboxSortDirection, InboxSortField } from '../../logics/inboxFiltersLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import {
    INBOX_REPORT_SECTION_KEYS,
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
} from '../../types'
import { compareSignalReports } from '../../utils/reportOrdering'
import { CardSkeleton } from '../cards/CardSkeleton'
import { ReportCard } from '../cards/ReportCard'
import { InboxWaitingForWork } from '../emptyState/InboxWaitingForWork'
import { SelfDrivingInstallingHint } from '../SelfDrivingInstallingHint'
import { InboxBulkSelectionBar } from '../shell/InboxBulkSelectionBar'
import { InboxReportFilters } from '../shell/InboxReportFilters'
import { InboxScopeFilter } from '../shell/InboxScopeFilter'
import { ReportRankEntry, useReportImpressions } from '../useReportImpressions'

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
    reportsResponseLoading: boolean
    hasMore: boolean
}

/**
 * Read one value at a time rather than spreading what `useValues` returns: it hands back a proxy
 * whose properties are subscribing getters, and spreading it yields an empty object — silently, and
 * with a type that still claims every value is there.
 */
function useSectionState(sectionKey: InboxReportSectionKey): SectionListState {
    const { count, countLoading, reports, isLoaded, reportsLoadFailed, reportsResponseLoading, hasMore } = useValues(
        reportListLogic(sectionListLogicProps(sectionKey))
    )
    return { count, countLoading, reports, isLoaded, reportsLoadFailed, reportsResponseLoading, hasMore }
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
 * One event per visit; it carries the whole loaded list rather than one view's slice.
 */
function useInboxViewedEvent(sections: Record<CountedSectionKey, SectionListState>): void {
    const { hasActiveFilters, sourceProductFilter, priorityFilter, stateFilter, scope } = useValues(inboxFiltersLogic)
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
            // pinned: `tab` names the inbox page tab. Before the flat list landed it named the report
            // view, which is no longer a surface of its own.
            tab: 'reports',
            reports: COUNTED_SECTION_KEYS.flatMap((key) => sections[key].reports),
            totalCount: COUNTED_SECTION_KEYS.reduce((sum, key) => sum + (sections[key].count ?? 0), 0),
            pullsTabCount: sections.monitoring.count,
            reportsTabCount: sections['needs-decision'].count,
            hasActiveFilters,
            sourceProductFilter,
            priorityFilter,
            stateFilter,
            scope,
        })
    }, [listVisible, settled, sections, hasActiveFilters, sourceProductFilter, priorityFilter, stateFilter, scope])
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

interface ReportRow {
    report: SignalReport
    sectionKey: InboxReportSectionKey
}

/**
 * The flat list's rows: the loaded rows of every selected state, deduplicated (a report can match
 * two states' filters, e.g. a PR'd report judged not actionable is in both Review and merge and the
 * staff Not actionable state), then ordered with the same keys the server sorted each response by.
 * Rows past a state's loaded page can sort below later-keyed rows from a shorter state until the
 * next page lands; the scroll sentinel keeps every selected state paging together.
 */
function mergeRows(
    sections: Record<InboxReportSectionKey, SectionListState>,
    selected: InboxReportSectionKey[],
    sortField: InboxSortField,
    sortDirection: InboxSortDirection
): ReportRow[] {
    const seen = new Set<string>()
    const rows: ReportRow[] = []
    for (const sectionKey of selected) {
        for (const report of sections[sectionKey].reports) {
            if (!seen.has(report.id)) {
                seen.add(report.id)
                rows.push({ report, sectionKey })
            }
        }
    }
    const compare = compareSignalReports(sortField, sortDirection)
    return rows.sort((a, b) => compare(a.report, b.report))
}

/** Headless per-state controller: loads the state's rows and records their impressions. */
function StateListController({
    sectionKey,
    rankById,
}: {
    sectionKey: InboxReportSectionKey
    rankById: Map<string, ReportRankEntry>
}): null {
    const { ensureLoaded } = useActions(reportListLogic(sectionListLogicProps(sectionKey)))
    // Rows are fetched once a state is part of the rendered list — a deselected state costs one
    // count request only.
    useEffect(() => {
        ensureLoaded()
    }, [ensureLoaded])
    useReportImpressions(sectionKey, rankById)
    return null
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
    const { hasActiveFilters, stateFilter, scope, sortField, sortDirection } = useValues(inboxFiltersLogic)
    const sections = useSectionStates()
    useInboxViewedEvent(sections)

    const visibleSections: InboxReportSectionKey[] = INBOX_REPORT_SECTION_KEYS.filter(
        (key) => isStaff || !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)
    )
    // The state filter narrows which states' rows the list shows, but only over states this user can
    // see: a shared link can carry the staff-only state, so intersect it with the staff gate first.
    // An empty effective selection — no filter, or a filter naming only states the user can't see —
    // means all visible states, so a non-staff user who opens a `state=not-actionable` link still
    // sees the full list rather than an empty one with no checkbox left to clear it.
    const effectiveStateFilter = visibleSections.filter((key) => stateFilter.includes(key))
    const selectedSections = effectiveStateFilter.length > 0 ? effectiveStateFilter : visibleSections

    // "Nothing yet" is a claim about the whole project, so it only holds with no filters and the
    // project-wide scope; a narrowed view that matches nothing gets the filter-aware copy instead.
    // The verdict is over the states this user can see, so staff still reach Not actionable when it
    // is the only state with reports. Hold the list until every count has answered, so a slow first
    // load never flashes the "nothing yet" screen at a full inbox.
    const narrowed = hasActiveFilters || effectiveStateFilter.length > 0
    const unfilteredView = !narrowed && scope === INBOX_SCOPE_ENTIRE_PROJECT
    const countsSettled = visibleSections.every((key) => sections[key].count !== null)
    const inboxIsEmpty = unfilteredView && countsSettled && visibleSections.every((key) => sections[key].count === 0)

    const rows = mergeRows(sections, selectedSections, sortField, sortDirection)
    const rankById = new Map<string, ReportRankEntry>(
        rows.map((row, index) => [row.report.id, { rank: index + 1, sectionKey: row.sectionKey }])
    )

    const firstLoadPending = selectedSections.some((key) => !sections[key].isLoaded && !sections[key].reportsLoadFailed)
    const anyLoadFailed = selectedSections.some((key) => sections[key].reportsLoadFailed && !sections[key].isLoaded)
    const pageLoading = selectedSections.some((key) => sections[key].reportsResponseLoading)
    const hasMore = selectedSections.some((key) => sections[key].hasMore)

    // `ensureLoaded` only fetches a state with nothing loaded and nothing in flight, so retrying
    // after a partial failure refetches the failed states and leaves the loaded ones alone.
    const retryFailedSections = (): void => {
        selectedSections.forEach((key) => reportListLogic(sectionListLogicProps(key)).actions.ensureLoaded())
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

            {selectedSections.map((sectionKey) => (
                <StateListController key={sectionKey} sectionKey={sectionKey} rankById={rankById} />
            ))}

            {inboxIsEmpty ? (
                <ReportsEmptyState />
            ) : rows.length === 0 ? (
                firstLoadPending ? (
                    <CardSkeleton count={4} variant="cards" dashed />
                ) : anyLoadFailed ? (
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
                        <ReportCard
                            key={report.id}
                            report={report}
                            sectionKey={sectionKey}
                            onRestore={() =>
                                reportListLogic(sectionListLogicProps(sectionKey)).actions.restoreReport(report.id)
                            }
                        />
                    ))}
                    {/* Skeleton cards continue the list while more rows load – sleeker than a spinner. */}
                    {(firstLoadPending || pageLoading) && <CardSkeleton count={2} variant="cards" dashed />}
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
                    {hasMore && <div ref={sentinelRef} className="h-1" aria-hidden />}
                </div>
            )}
        </div>
    )
}
