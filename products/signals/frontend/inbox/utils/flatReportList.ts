import { isMergeKeySortField } from '../filterOptions'
import type { InboxSortDirection, InboxSortField } from '../logics/inboxFiltersLogic'
import {
    INBOX_REPORT_SECTION_KEYS,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    InboxReportSectionKey,
    SignalReport,
} from '../types'
import { compareSignalReports } from './reportOrdering'
import { hasActiveReportPullRequest } from './reportPullRequests'

/** One row of the flat Reports list: the report and the state whose response contributed it. */
export interface MergedReportRow {
    report: SignalReport
    sectionKey: InboxReportSectionKey
    /** The other loaded reports of the same plan that this row stands for, when plan layers collapse. */
    collapsedReportIds?: string[]
    /**
     * The report whose place in the order a collapsed card took, when the card shows a different report.
     * Order-dependent reads, such as where the unscored rows start, read this one.
     */
    slotReport?: SignalReport
}

/**
 * The states the flat Reports list shows, in canonical order: the state filter's selection when it
 * has one, every state the user can see otherwise. Shared by the list itself and by the analytics
 * rank lookup in `inboxSceneLogic`, so an opened report's rank is computed over the same rows the
 * user saw.
 */
export function selectedFlatListSections(
    visibleStateFilter: InboxReportSectionKey[],
    isStaff: boolean
): InboxReportSectionKey[] {
    const visibleSections = INBOX_REPORT_SECTION_KEYS.filter(
        (key) => isStaff || !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)
    )
    return visibleStateFilter.length > 0
        ? visibleSections.filter((key) => visibleStateFilter.includes(key))
        : visibleSections
}

/**
 * Merge per-state rows that are each already in server order. Each step takes the state head with the
 * lowest key, and an earlier state wins a tie. Unlike a sort, this keeps each response's own order,
 * which the server set from finer data than the merge key carries.
 */
function mergeSortedSections(
    rowsBySection: MergedReportRow[][],
    compare: (a: SignalReport, b: SignalReport) => number
): MergedReportRow[] {
    const cursors = rowsBySection.map(() => 0)
    const merged: MergedReportRow[] = []
    for (;;) {
        let best = -1
        rowsBySection.forEach((rows, index) => {
            if (
                cursors[index] < rows.length &&
                (best === -1 || compare(rows[cursors[index]].report, rowsBySection[best][cursors[best]].report) < 0)
            ) {
                best = index
            }
        })
        if (best === -1) {
            return merged
        }
        merged.push(rowsBySection[best][cursors[best]])
        cursors[best] += 1
    }
}

/**
 * The flat list's rows: the loaded rows of every selected state, deduplicated (a report can match
 * two states' filters, e.g. a PR'd report judged not actionable is in both Review and merge and the
 * staff Not actionable state; the first state in canonical order claims it), then ordered with the
 * same keys the server sorted each response by. The Recommended sort merges the
 * responses by the server's merge key instead, because the server orders each response by a score it does not send.
 * Rows past a state's loaded page can sort below later-keyed rows from a shorter state until the
 * next page lands; the scroll sentinel keeps every selected state paging together.
 */
export function mergeReportRows(
    reportsBySection: Record<InboxReportSectionKey, SignalReport[]>,
    selectedSections: InboxReportSectionKey[],
    sortField: InboxSortField,
    sortDirection: InboxSortDirection,
    { collapsePlans = false }: { collapsePlans?: boolean } = {}
): MergedReportRow[] {
    const seen = new Set<string>()
    const rowsBySection: MergedReportRow[][] = []
    for (const sectionKey of selectedSections) {
        const sectionRows: MergedReportRow[] = []
        for (const report of reportsBySection[sectionKey]) {
            if (!seen.has(report.id)) {
                seen.add(report.id)
                sectionRows.push({ report, sectionKey })
            }
        }
        rowsBySection.push(sectionRows)
    }
    const compare = compareSignalReports(sortField, sortDirection)
    const rows = isMergeKeySortField(sortField)
        ? mergeSortedSections(rowsBySection, compare)
        : rowsBySection.flat().sort((a, b) => compare(a.report, b.report))
    return collapsePlans ? collapsePlanRows(rows) : rows
}

/**
 * The plan a row collapses into: the plan it is a layer of, or its own id when it is the plan. A plan
 * with its own pull request in flight keeps its own card, because hiding it would hide that review.
 */
function planKey(report: SignalReport): string | null {
    const summary = report.link_summary
    if (!summary?.plan || (summary.kind !== 'part_of' && summary.kind !== 'plan')) {
        return null
    }
    if (summary.kind === 'plan' && hasActiveReportPullRequest(report)) {
        return null
    }
    return summary.plan.id
}

/**
 * Show each plan as one card, at the place of its best-ranked loaded row, so a plan never sorts below its
 * strongest layer. The card is the plan's lead layer when that layer is loaded, else the best-ranked
 * loaded layer, else the plan itself. Only loaded rows collapse, so a filter that matches some layers
 * collapses over those, and a layer that arrives on a later page joins the card already shown.
 */
export function collapsePlanRows(rows: MergedReportRow[]): MergedReportRow[] {
    const members = new Map<string, MergedReportRow[]>()
    for (const row of rows) {
        const key = planKey(row.report)
        if (key) {
            members.set(key, [...(members.get(key) ?? []), row])
        }
    }
    const collapsed: MergedReportRow[] = []
    const shown = new Set<string>()
    for (const row of rows) {
        const key = planKey(row.report)
        if (!key) {
            collapsed.push(row)
            continue
        }
        if (shown.has(key)) {
            continue
        }
        shown.add(key)
        const group = members.get(key) ?? [row]
        const layers = group.filter((member) => member.report.id !== key)
        const card =
            layers.find((member) => member.report.link_summary?.plan?.lead_step_id === member.report.id) ??
            layers[0] ??
            row
        collapsed.push({
            ...card,
            collapsedReportIds: group.filter((member) => member !== card).map((member) => member.report.id),
            ...(card !== row ? { slotReport: row.report } : {}),
        })
    }
    return collapsed
}
