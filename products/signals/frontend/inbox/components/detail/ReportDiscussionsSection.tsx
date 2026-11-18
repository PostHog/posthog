import { useActions, useValues } from 'kea'

import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { captureInboxReportAction, captureInboxRunSummaryViewed } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic, ReportDiscussion } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { ReportDiscussionRow } from './ReportDiscussionRow'

/**
 * The Ask AI chats people started on the report, at the end of its body next to the notes. The
 * section renders nothing until the report's tasks load, and nothing for a report with no chats.
 */
export function ReportDiscussionsSection({ report }: { report: SignalReport }): JSX.Element | null {
    const logic = inboxReportDetailLogic({ reportId: report.id, report })
    const { reportDiscussions, expandedTaskIds } = useValues(logic)
    const { toggleExpandedTask } = useActions(logic)
    const { openReportTask } = useActions(inboxTaskKickoffLogic)

    if (!reportDiscussions || reportDiscussions.length === 0) {
        return null
    }

    const toggle = ({ entry }: ReportDiscussion, expanded: boolean): void => {
        const summary = entry.task.latest_run?.task_summary?.trim()
        if (!expanded && summary) {
            captureInboxRunSummaryViewed({
                purpose: entry.purpose,
                status: entry.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED,
                summaryLength: summary.length,
                surface: 'discussion_list',
            })
        }
        toggleExpandedTask(entry.task.id)
    }

    const openChat = ({ entry }: ReportDiscussion, runId: string): void => {
        captureInboxReportAction({
            report,
            actionType: 'resume_discussion',
            surface: 'detail_pane',
            extra: { source: 'discussion_list' },
        })
        openReportTask(report, entry.task.id, runId)
    }

    return (
        <div className="mb-4 flex flex-col gap-2" data-attr="inbox-report-discussions">
            <span className="text-xs font-semibold text-secondary">
                <span>Ask AI chats · </span>
                <span translate="no">{reportDiscussions.length}</span>
            </span>
            <div className="flex flex-col rounded border border-primary bg-surface-primary">
                {reportDiscussions.map((discussion) => {
                    const expanded = expandedTaskIds.includes(discussion.entry.task.id)
                    return (
                        <ReportDiscussionRow
                            key={discussion.entry.task.id}
                            discussion={discussion}
                            expanded={expanded}
                            onToggle={() => toggle(discussion, expanded)}
                            onOpenChat={(runId) => openChat(discussion, runId)}
                        />
                    )
                })}
            </div>
        </div>
    )
}
