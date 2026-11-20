import { userLogic } from 'scenes/userLogic'

import { inboxFiltersLogic } from '../logics/inboxFiltersLogic'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic } from '../logics/reportListLogic'
import { INBOX_REPORT_SECTION_KEYS, InboxReportSectionKey, SignalReport } from '../types'
import { mergeReportRows, selectedFlatListSections } from './flatReportList'

export interface InboxReportQueue {
    position: number
    total: number
    previousId: string | null
    nextId: string | null
}

export function reportQueuePosition(orderedIds: string[], total: number, reportId: string): InboxReportQueue | null {
    const index = orderedIds.indexOf(reportId)
    if (index < 0) {
        return null
    }
    return {
        position: index + 1,
        total: Math.max(total, orderedIds.length),
        previousId: orderedIds[index - 1] ?? null,
        nextId: orderedIds[index + 1] ?? null,
    }
}

/**
 * The report's place in the Reports list, in the order and with the filters the person saw. Null when the
 * list is not mounted or does not hold the report, for example after a cold open from a link.
 */
export function inboxReportQueue(reportId: string): InboxReportQueue | null {
    const filterValues = inboxFiltersLogic.findMounted()?.values
    if (!filterValues) {
        return null
    }
    const isStaff = userLogic.findMounted()?.values.user?.is_staff ?? false
    const selectedSections = selectedFlatListSections(filterValues.visibleStateFilter, isStaff)
    const sectionValues = (sectionKey: InboxReportSectionKey): { reports: SignalReport[]; count: number | null } => {
        const values = reportListLogic.findMounted({
            sectionKey,
            listParams: INBOX_REPORT_SECTION_LIST_PARAMS[sectionKey],
        })?.values
        return { reports: values?.reports ?? [], count: values?.count ?? null }
    }
    const reportsBySection = Object.fromEntries(
        INBOX_REPORT_SECTION_KEYS.map((sectionKey) => [sectionKey, sectionValues(sectionKey).reports])
    ) as Record<InboxReportSectionKey, SignalReport[]>
    const rows = mergeReportRows(
        reportsBySection,
        selectedSections,
        filterValues.activeSortField,
        filterValues.activeSortDirection
    )
    const total = selectedSections.reduce((sum, sectionKey) => sum + (sectionValues(sectionKey).count ?? 0), 0)
    return reportQueuePosition(
        rows.map((row) => row.report.id),
        total,
        reportId
    )
}
