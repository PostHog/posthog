import { BindLogic, useActions, useValues } from 'kea'
import { ComponentType, JSX, useCallback, useEffect, useRef } from 'react'

import { captureInboxReportsImpressed, captureInboxViewed } from '../inboxAnalytics'
import { inboxSceneLogic } from '../inboxSceneLogic'
import { inboxFiltersLogic } from '../logics/inboxFiltersLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic, ReportListLogicProps } from '../logics/reportListLogic'
import { INBOX_LEGACY_TAB_SECTION, InboxFlatListTabKey, InboxReportSectionKey, SignalReport } from '../types'
import { DismissalReasonValue } from '../utils/dismissalReasons'
import { CardSkeleton } from './cards/CardSkeleton'
import { InboxBulkSelectionBar } from './shell/InboxBulkSelectionBar'
import { InboxSearchFilterBar } from './shell/InboxSearchFilterBar'

export interface InboxReportCardProps {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    onArchive: (reason: DismissalReasonValue, note: string) => void
    /** Restore a suppressed report back to the inbox. Only wired on the Archived tab. */
    onRestore?: () => void
    /** Rendered as an attached row inside a shared bordered container (vs. a freestanding card). */
    attached?: boolean
}

interface InboxReportListProps {
    tabKey: InboxFlatListTabKey
    Card: ComponentType<InboxReportCardProps>
    emptyState:
        | { content: JSX.Element }
        | { icon: JSX.Element; title: string; description: string; extra?: JSX.Element }
}

/** The keyed list instance behind a legacy tab: the redesign's section with the same server filter. */
function sectionLogicProps(tabKey: InboxFlatListTabKey): ReportListLogicProps {
    const sectionKey = INBOX_LEGACY_TAB_SECTION[tabKey]
    return { sectionKey, listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey] }
}

/**
 * Shared body for the flat report-list tabs shown with the redesign flag off (Pull requests /
 * Reports / Not actionable / Archive). Each is the same primitive – only the server filter and
 * the empty-state copy differ. Binds the keyed `reportListLogic`, loads the first
 * page lazily on mount, shows a skeleton while a known-non-empty tab loads, and
 * appends pages via an IntersectionObserver sentinel.
 */
export function InboxReportList(props: InboxReportListProps): JSX.Element {
    return (
        <BindLogic logic={reportListLogic} props={sectionLogicProps(props.tabKey)}>
            <InboxReportListInner {...props} />
        </BindLogic>
    )
}

function InboxReportListInner({ tabKey, Card, emptyState }: InboxReportListProps): JSX.Element {
    const { reports, count, totalCount, hasMore, reportsResponseLoading, isLoaded, loadedQueryKey, loadedContext } =
        useValues(reportListLogic)
    const { ensureLoaded, loadMore, archiveReport, restoreReport, refresh } = useActions(reportListLogic)
    const { hasActiveFilters, sourceProductFilter, priorityFilter, scope } = useValues(inboxFiltersLogic)
    // The list stays mounted (hidden) while a report/scout detail is open, so gate the view event on
    // the list actually being the visible surface — otherwise a deep-link to a report fires a phantom
    // `Inbox viewed` and then suppresses the real one when the user navigates back to the list.
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen } = useValues(inboxSceneLogic)
    const listVisible = !selectedReportId && !selectedScoutSkillName && !isScratchpadOpen && !isFindingsOpen

    // The Pull requests / Reports badge counts go on every `Inbox viewed`, whatever tab is open: the
    // active tab's `total_count` alone says nothing about a user who lands on Pull requests and has
    // 200 reports waiting. These share the tab bar's keyed instances, so no extra requests.
    const { count: pullsTabCount, countLoading: pullsTabCountLoading } = useValues(
        reportListLogic(sectionLogicProps('pulls'))
    )
    const { count: reportsTabCount, countLoading: reportsTabCountLoading } = useValues(
        reportListLogic(sectionLogicProps('reports'))
    )
    // A badge count is settled once its request is no longer in flight: loaded, refreshed, or failed
    // (count stays null). Waiting on the loading flags rather than non-null values means a scope or
    // filter refresh in progress doesn't fire the event with the previous query's counts.
    const badgeCountsSettled = !pullsTabCountLoading && !reportsTabCountLoading

    // Fire `Inbox viewed` once per tab mount, the first time its list and the badge counts settle
    // while visible.
    const viewedFiredRef = useRef(false)
    useEffect(() => {
        if (listVisible && isLoaded && count !== null && badgeCountsSettled && !viewedFiredRef.current) {
            viewedFiredRef.current = true
            captureInboxViewed({
                tab: tabKey,
                reports,
                totalCount: count,
                pullsTabCount,
                reportsTabCount,
                hasActiveFilters,
                sourceProductFilter,
                priorityFilter,
                scope,
            })
        }
    }, [
        listVisible,
        isLoaded,
        count,
        badgeCountsSettled,
        pullsTabCount,
        reportsTabCount,
        reports,
        tabKey,
        hasActiveFilters,
        sourceProductFilter,
        priorityFilter,
        scope,
    ])

    // Impression log for ranking-model training: record each report the first time it appears in
    // the visible list (initial page, pagination, refresh), with its rank at that moment. Deduped
    // per tab mount so re-renders and detail-pane round-trips don't refire.
    const impressedIdsRef = useRef(new Set<string>())
    // Dedupe is per query: a sort/search/filter/scope change is a new ranking context, so a report
    // re-shown under the new query must impress again (at its new rank) for its later open/action
    // events to have a matching impression.
    const impressionQueryKeyRef = useRef('')
    useEffect(() => {
        // totalCount, loadedQueryKey, and loadedContext come from the same response as `reports`
        // (not the live filter state or the separately-loaded badge count), so impressions can't
        // be stamped with a stale total or with scope/filter context the user switched to after
        // the request went out, and rows from the previous query are never attributed to the new
        // one while its refetch is still in flight.
        if (!listVisible || !isLoaded || totalCount === null || loadedQueryKey === null || loadedContext === null) {
            return
        }
        if (loadedQueryKey !== impressionQueryKeyRef.current) {
            impressionQueryKeyRef.current = loadedQueryKey
            impressedIdsRef.current = new Set<string>()
        }
        const fresh = reports
            .map((report, index) => ({ report, rank: index + 1 }))
            .filter(({ report }) => !impressedIdsRef.current.has(report.id))
        if (fresh.length === 0) {
            return
        }
        fresh.forEach(({ report }) => impressedIdsRef.current.add(report.id))
        captureInboxReportsImpressed({
            tab: tabKey,
            reports: fresh.map(({ report }) => report),
            ranks: fresh.map(({ rank }) => rank),
            listSize: reports.length,
            totalCount,
            hasActiveFilters: loadedContext.hasActiveFilters,
            scope: loadedContext.scope,
        })
    }, [listVisible, isLoaded, totalCount, reports, tabKey, loadedQueryKey, loadedContext])

    // Read fresh state at intersection time via refs so the observer isn't rebuilt twice per page
    // fetch (`hasMore`/`reportsResponseLoading` both flip during a load).
    const hasMoreRef = useRef(hasMore)
    hasMoreRef.current = hasMore
    const loadingRef = useRef(reportsResponseLoading)
    loadingRef.current = reportsResponseLoading

    useEffect(() => {
        ensureLoaded()
    }, [ensureLoaded])

    // A callback ref, not an effect over `sentinelRef`: the sentinel only enters the DOM once the
    // first page has landed and `hasMore` is true, which is after a mount-only effect has already
    // run and found nothing to observe. Attaching as the node mounts is what keeps paging alive.
    const observerRef = useRef<IntersectionObserver | null>(null)
    const sentinelRef = useCallback(
        (el: HTMLDivElement | null) => {
            observerRef.current?.disconnect()
            observerRef.current = null
            if (!el) {
                return
            }
            const observer = new IntersectionObserver(
                (entries) => {
                    if (entries[0]?.isIntersecting && hasMoreRef.current && !loadingRef.current) {
                        loadMore()
                    }
                },
                // Generous prefetch margin so the next page lands well before the user reaches the bottom.
                { rootMargin: '1500px' }
            )
            observer.observe(el)
            observerRef.current = observer
        },
        [loadMore]
    )
    useEffect(() => () => observerRef.current?.disconnect(), [])

    // Skeleton while a tab we know is non-empty loads its first page.
    const showSkeleton = !isLoaded && (reportsResponseLoading || (count ?? 0) > 0)

    return (
        <div className="@container mx-auto max-w-4xl flex flex-col gap-4 px-6 py-4">
            <InboxSearchFilterBar onRefresh={() => refresh()} refreshing={reportsResponseLoading} />
            <InboxBulkSelectionBar />

            {showSkeleton ? (
                <CardSkeleton count={Math.min(count ?? 4, 6)} variant="cards" dashed={tabKey !== 'pulls'} />
            ) : reports.length === 0 ? (
                'content' in emptyState ? (
                    emptyState.content
                ) : (
                    <div className="mx-auto max-w-md flex flex-col items-center text-center py-12 gap-2">
                        <div className="flex items-center justify-center h-12 w-12 rounded-full bg-fill-primary text-secondary mb-1">
                            {emptyState.icon}
                        </div>
                        <h3 className="text-base font-semibold m-0">{emptyState.title}</h3>
                        <p className="text-sm text-tertiary m-0">{emptyState.description}</p>
                        {emptyState.extra}
                    </div>
                )
            ) : (
                <>
                    {/* Each report is its own freestanding card, separated by a small gap. */}
                    <div className="flex flex-col gap-1.5">
                        {reports.map((report) => (
                            <Card
                                key={report.id}
                                report={report}
                                sectionKey={INBOX_LEGACY_TAB_SECTION[tabKey]}
                                onArchive={(reason, note) => archiveReport(report.id, reason, note)}
                                onRestore={() => restoreReport(report.id)}
                            />
                        ))}
                        {/* Skeleton cards continue the list while the next page loads – sleeker than a spinner. */}
                        {isLoaded && reportsResponseLoading && (
                            <CardSkeleton count={2} variant="cards" dashed={tabKey !== 'pulls'} />
                        )}
                    </div>
                    {hasMore && <div ref={sentinelRef} className="h-1" aria-hidden />}
                </>
            )}
        </div>
    )
}
