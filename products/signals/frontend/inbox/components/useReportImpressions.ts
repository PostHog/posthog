import { useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { captureInboxReportsImpressed } from '../inboxAnalytics'
import { inboxSceneLogic } from '../inboxSceneLogic'
import { reportListLogic, sectionListLogicProps } from '../logics/reportListLogic'
import { InboxReportSectionKey } from '../types'
import type { MergedReportRow } from '../utils/flatReportList'

interface SectionImpressionState {
    isLoaded: boolean
    reportsLoadFailed: boolean
    reportsResponseLoading: boolean
    totalCount: number | null
    loadedQueryKey: string | null
    loadedContext: { scope: string; hasActiveFilters: boolean } | null
}

function useSectionImpressionState(sectionKey: InboxReportSectionKey): SectionImpressionState {
    const { isLoaded, reportsLoadFailed, reportsResponseLoading, totalCount, loadedQueryKey, loadedContext } =
        useValues(reportListLogic(sectionListLogicProps(sectionKey)))
    return { isLoaded, reportsLoadFailed, reportsResponseLoading, totalCount, loadedQueryKey, loadedContext }
}

/**
 * Impression log for ranking-model training: record each rendered report the first time it is
 * actually on screen in the flat list, with its rank there at that moment. One hook for the whole
 * list, with one dedupe set, so a report matching two states' filters is recorded once however the
 * state requests interleave. Impressions wait until every selected state's request has settled, so
 * the recorded ranks are the merged order the user actually sees, not a fast state's provisional
 * one. The context key covers the state selection and each selected state's loaded query, so
 * narrowing the state filter or changing any server filter re-impresses the rows at their new
 * ranks; loading a further page keeps the context and impresses only the new rows.
 */
export function useReportImpressions(rows: MergedReportRow[], selectedSections: InboxReportSectionKey[]): void {
    // Fixed-order reads over every state (not just the selected ones), so the hook order never
    // changes when the filter does; the effect below only consults the selected states.
    const sections: Record<InboxReportSectionKey, SectionImpressionState> = {
        monitoring: useSectionImpressionState('monitoring'),
        'needs-decision': useSectionImpressionState('needs-decision'),
        resolved: useSectionImpressionState('resolved'),
        dismissed: useSectionImpressionState('dismissed'),
        'not-actionable': useSectionImpressionState('not-actionable'),
    }
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

    // Settled: every selected state answered (rows landed, or the request failed) with nothing in
    // flight, so the merged rows are stable until the user or a pager changes the query.
    const settled = selectedSections.every(
        (key) => (sections[key].isLoaded || sections[key].reportsLoadFailed) && !sections[key].reportsResponseLoading
    )
    const contextKey = JSON.stringify(selectedSections.map((key) => [key, sections[key].loadedQueryKey]))

    const impressedIdsRef = useRef(new Set<string>())
    const impressionContextKeyRef = useRef('')
    useEffect(() => {
        if (!listVisible || !settled) {
            return
        }
        // Track the context even when it matches nothing, so coming back to an earlier query is a
        // fresh ranking context and its rows impress again.
        if (contextKey !== impressionContextKeyRef.current) {
            impressionContextKeyRef.current = contextKey
            impressedIdsRef.current = new Set<string>()
        }
        if (rows.length === 0) {
            return
        }
        const fresh = rows
            .map((row, index) => ({ ...row, rank: index + 1 }))
            .filter(({ report }) => !impressedIdsRef.current.has(report.id))
        if (fresh.length === 0) {
            return
        }
        fresh.forEach(({ report }) => impressedIdsRef.current.add(report.id))
        // One event per contributing state: `tab` and `totalCount` describe the state's own query,
        // while ranks and list size describe the merged list the rows actually rendered in.
        const sectionKeys = [...new Set(fresh.map(({ sectionKey }) => sectionKey))]
        for (const sectionKey of sectionKeys) {
            const context = sections[sectionKey].loadedContext
            if (!context) {
                continue
            }
            const sectionRows = fresh.filter((row) => row.sectionKey === sectionKey)
            captureInboxReportsImpressed({
                tab: sectionKey,
                reports: sectionRows.map(({ report }) => report),
                ranks: sectionRows.map(({ rank }) => rank),
                listSize: rows.length,
                totalCount: sections[sectionKey].totalCount,
                hasActiveFilters: context.hasActiveFilters,
                scope: context.scope,
            })
        }
        // `sections` is a fresh object each render; `contextKey` and `settled` already change with
        // every value the capture reads from it.
        // oxlint-disable-next-line react-hooks/exhaustive-deps
    }, [listVisible, settled, contextKey, rows])
}
