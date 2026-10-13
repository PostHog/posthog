import type { InboxSortDirection, InboxSortField } from '../logics/inboxFiltersLogic'
import {
    INBOX_REPORT_SECTION_KEYS,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    InboxReportSectionKey,
    SignalReport,
} from '../types'
import { compareSignalReports } from './reportOrdering'

/** One row of the flat Reports list: the report and the state whose response contributed it. */
export interface MergedReportRow {
    report: SignalReport
    sectionKey: InboxReportSectionKey
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
 * The flat list's rows: the loaded rows of every selected state, deduplicated (a report can match
 * two states' filters, e.g. a PR'd report judged not actionable is in both Review and merge and the
 * staff Not actionable state; the first state in canonical order claims it), then ordered with the
 * same keys the server sorted each response by. Rows past a state's loaded page can sort below
 * later-keyed rows from a shorter state until the next page lands; the scroll sentinel keeps every
 * selected state paging together.
 */
export function mergeReportRows(
    reportsBySection: Record<InboxReportSectionKey, SignalReport[]>,
    selectedSections: InboxReportSectionKey[],
    sortField: InboxSortField,
    sortDirection: InboxSortDirection
): MergedReportRow[] {
    const seen = new Set<string>()
    const rows: MergedReportRow[] = []
    for (const sectionKey of selectedSections) {
        for (const report of reportsBySection[sectionKey]) {
            if (!seen.has(report.id)) {
                seen.add(report.id)
                rows.push({ report, sectionKey })
            }
        }
    }
    const compare = compareSignalReports(sortField, sortDirection)
    return rows.sort((a, b) => compare(a.report, b.report))
}
