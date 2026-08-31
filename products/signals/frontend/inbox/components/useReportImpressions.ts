import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { captureInboxReportsImpressed } from '../inboxAnalytics'
import { inboxSceneLogic } from '../inboxSceneLogic'
import { reportListLogic, sectionListLogicProps } from '../logics/reportListLogic'
import { InboxReportSectionKey, SignalReport } from '../types'

/** Where one report sits in the flat list: its 1-based rank and the state that contributed it. */
export interface ReportRankEntry {
    rank: number
    sectionKey: InboxReportSectionKey
}

/**
 * Impression log for ranking-model training: record each report the first time it is actually on
 * screen in the flat list, with its rank there at that moment. `rankById` covers the whole merged
 * list; this hook impresses only the rows this state contributed, so a report matching two states'
 * filters is recorded once, under the state that claimed it. A state the filter deselects mounts no
 * hook and impresses nothing. Deduped per mount so re-renders and detail-pane round-trips don't
 * refire.
 */
export function useReportImpressions(sectionKey: InboxReportSectionKey, rankById: Map<string, ReportRankEntry>): void {
    const { reports, totalCount, isLoaded, loadedQueryKey, loadedContext } = useValues(
        reportListLogic(sectionListLogicProps(sectionKey))
    )
    // The list stays mounted (hidden) while a report/scout detail is open, so gate impressions on the
    // list actually being the visible surface.
    const { selectedReportId, selectedScoutSkillName, isScratchpadOpen, isFindingsOpen, isRunsOpen, isTriageOpen } =
        useValues(inboxSceneLogic)
    const listVisible =
        !selectedReportId &&
        !selectedScoutSkillName &&
        !isScratchpadOpen &&
        !isFindingsOpen &&
        !isRunsOpen &&
        !isTriageOpen

    const impressedIdsRef = useRef(new Set<string>())
    // Dedupe is per query: a sort/search/filter/scope change is a new ranking context, so a report
    // re-shown under the new query must impress again (at its new rank) for its later open/action
    // events to have a matching impression.
    const impressionQueryKeyRef = useRef('')
    useEffect(() => {
        // totalCount, loadedQueryKey, and loadedContext come from the same response as the rows (not
        // the live filter state or the separately-loaded count), so impressions can't be stamped
        // with a stale total or with scope/filter context the user switched to after the request
        // went out, and rows from the previous query are never attributed to the new one while its
        // refetch is still in flight.
        if (!listVisible || !isLoaded || totalCount === null || loadedQueryKey === null || loadedContext === null) {
            return
        }
        if (loadedQueryKey !== impressionQueryKeyRef.current) {
            impressionQueryKeyRef.current = loadedQueryKey
            impressedIdsRef.current = new Set<string>()
        }
        const fresh = reports
            .map((report) => ({ report, entry: rankById.get(report.id) }))
            .filter(
                (item): item is { report: SignalReport; entry: ReportRankEntry } =>
                    item.entry?.sectionKey === sectionKey && !impressedIdsRef.current.has(item.report.id)
            )
        if (fresh.length === 0) {
            return
        }
        fresh.forEach(({ report }) => impressedIdsRef.current.add(report.id))
        captureInboxReportsImpressed({
            tab: sectionKey,
            reports: fresh.map(({ report }) => report),
            ranks: fresh.map(({ entry }) => entry.rank),
            listSize: rankById.size,
            totalCount,
            hasActiveFilters: loadedContext.hasActiveFilters,
            scope: loadedContext.scope,
        })
    }, [listVisible, isLoaded, totalCount, reports, sectionKey, rankById, loadedQueryKey, loadedContext])
}
