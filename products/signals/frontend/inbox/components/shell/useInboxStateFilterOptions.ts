import { useValues } from 'kea'

import { inboxSceneLogic } from '../../inboxSceneLogic'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import {
    INBOX_REPORT_SECTION_KEYS,
    INBOX_REPORT_SECTION_LABEL,
    INBOX_STAFF_ONLY_REPORT_SECTION_KEYS,
    InboxReportSectionKey,
} from '../../types'

/**
 * The states the state filter offers, and the label for the current selection. Not actionable is for
 * staff only. Monitoring and Closed show only once the project has such reports or the selection holds them.
 */
export function useInboxStateFilterOptions(): { options: InboxReportSectionKey[]; label: string } {
    const { isStaff } = useValues(inboxSceneLogic)
    const { stateFilter, visibleStateFilter } = useValues(inboxFiltersLogic)
    const { hasProjectReports: hasProjectClosedReports } = useValues(reportListLogic(sectionListLogicProps('closed')))
    const { hasProjectReports: hasProjectMonitoringReports } = useValues(
        reportListLogic(sectionListLogicProps('outcome-monitoring'))
    )

    const options = INBOX_REPORT_SECTION_KEYS.filter(
        (key) =>
            (isStaff || !INBOX_STAFF_ONLY_REPORT_SECTION_KEYS.includes(key)) &&
            (key !== 'outcome-monitoring' || hasProjectMonitoringReports || stateFilter.includes(key)) &&
            (key !== 'closed' || hasProjectClosedReports || stateFilter.includes(key))
    )
    // Label from the visible selection: a shared link can carry the staff-only state, and the
    // trigger must not read "Not actionable" (or an inflated count) for a state whose checkbox the
    // dropdown hides and that does not narrow the list.
    const label =
        visibleStateFilter.length === 0
            ? 'All statuses'
            : visibleStateFilter.length === 1
              ? INBOX_REPORT_SECTION_LABEL[visibleStateFilter[0]]
              : `${visibleStateFilter.length} statuses`

    return { options, label }
}
