import { useActions, useValues } from 'kea'

import { IconTerminal } from '@posthog/icons'
import { LemonSkeleton } from '@posthog/lemon-ui'

import { inboxReportDetailLogic, ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { DetailSection } from './DetailSection'
import { ReportTaskRow } from './ReportTaskRow'

/**
 * Renders the report's linked tasks inline (latest status + purpose), each row expanding in place to
 * the task's run transcript — mirroring the Code experience instead of navigating away to a separate
 * run page. The purpose label is derived from each task's `task_run` artefact; `repo_selection` runs
 * are filtered out.
 */
export function ReportTasksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportTasks, reportTasksLoading, expandedTaskIds } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const { toggleExpandedTask } = useActions(inboxReportDetailLogic({ reportId: report.id, report }))

    if (reportTasksLoading && !reportTasks) {
        return (
            <DetailSection icon={<IconTerminal />} title="Runs" collapsible>
                <div className="flex flex-col gap-2 py-1">
                    <LemonSkeleton className="h-8 w-full" />
                    <LemonSkeleton className="h-8 w-full" />
                </div>
            </DetailSection>
        )
    }

    if (!reportTasks || reportTasks.length === 0) {
        return null
    }

    return (
        <DetailSection icon={<IconTerminal />} title="Runs" collapsible>
            <div className="flex flex-col gap-0.5">
                {reportTasks.map((entry: ReportTaskEntry) => (
                    <ReportTaskRow
                        key={entry.task.id}
                        entry={entry}
                        expanded={expandedTaskIds.includes(entry.task.id)}
                        onToggle={() => toggleExpandedTask(entry.task.id)}
                    />
                ))}
            </div>
        </DetailSection>
    )
}
