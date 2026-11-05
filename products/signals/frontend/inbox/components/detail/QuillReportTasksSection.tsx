import { useActions, useValues } from 'kea'

import { IconTerminal } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import { inboxReportDetailLogic, ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { QuillDetailSection } from './QuillDetailSection'
import { QuillReportTaskRow } from './QuillReportTaskRow'

/** The quill sibling of `ReportTasksSection`, for the report page behind `today-rail-nav`. */
export function QuillReportTasksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportTasks, reportTasksLoading, expandedTaskIds } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { toggleExpandedTask } = useActions(inboxReportDetailLogic({ reportId: report.id, report }))

    if (reportTasksLoading && !reportTasks) {
        return (
            <QuillDetailSection icon={<IconTerminal />} title="Runs" collapsible defaultCollapsed>
                <div className="flex flex-col gap-2 py-1">
                    <Skeleton className="h-8 w-full" />
                    <Skeleton className="h-8 w-full" />
                </div>
            </QuillDetailSection>
        )
    }

    if (!reportTasks || reportTasks.length === 0) {
        return null
    }

    return (
        <QuillDetailSection icon={<IconTerminal />} title="Runs" collapsible defaultCollapsed>
            <div className="flex flex-col gap-0.5">
                {reportTasks.map((entry: ReportTaskEntry) => (
                    <QuillReportTaskRow
                        key={entry.task.id}
                        entry={entry}
                        expanded={expandedTaskIds.includes(entry.task.id)}
                        onToggle={() => toggleExpandedTask(entry.task.id)}
                    />
                ))}
            </div>
        </QuillDetailSection>
    )
}
