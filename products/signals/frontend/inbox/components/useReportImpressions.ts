import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { captureInboxReportsImpressed } from '../inboxAnalytics'
import { inboxSceneLogic } from '../inboxSceneLogic'
import { reportListLogic } from '../logics/reportListLogic'
import { InboxReportSectionKey } from '../types'

/**
 * Impression log for ranking-model training: record each report the first time it is actually on
 * screen in this section, with its rank at that moment. A collapsed section impresses nothing.
 * Deduped per section mount so re-renders and detail-pane round-trips don't refire.
 */
export function useReportImpressions(sectionKey: InboxReportSectionKey, isOpen: boolean): void {
    const { visibleReports, totalCount, isLoaded, loadedQueryKey, loadedContext } = useValues(reportListLogic)
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
        // the live filter state or the separately-loaded header count), so impressions can't be
        // stamped with a stale total or with scope/filter context the user switched to after the
        // request went out, and rows from the previous query are never attributed to the new one
        // while its refetch is still in flight.
        if (
            !isOpen ||
            !listVisible ||
            !isLoaded ||
            totalCount === null ||
            loadedQueryKey === null ||
            loadedContext === null
        ) {
            return
        }
        if (loadedQueryKey !== impressionQueryKeyRef.current) {
            impressionQueryKeyRef.current = loadedQueryKey
            impressedIdsRef.current = new Set<string>()
        }
        const fresh = visibleReports
            .map((report, index) => ({ report, rank: index + 1 }))
            .filter(({ report }) => !impressedIdsRef.current.has(report.id))
        if (fresh.length === 0) {
            return
        }
        fresh.forEach(({ report }) => impressedIdsRef.current.add(report.id))
        captureInboxReportsImpressed({
            tab: sectionKey,
            reports: fresh.map(({ report }) => report),
            ranks: fresh.map(({ rank }) => rank),
            listSize: visibleReports.length,
            totalCount,
            hasActiveFilters: loadedContext.hasActiveFilters,
            scope: loadedContext.scope,
        })
    }, [isOpen, listVisible, isLoaded, totalCount, visibleReports, sectionKey, loadedQueryKey, loadedContext])
}
