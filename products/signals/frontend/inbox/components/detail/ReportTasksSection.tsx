import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconChevronDown, IconChevronRight, IconExternal, IconTerminal } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { inboxReportDetailLogic, ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { DetailSection } from './DetailSection'
import { RunLogContainer } from './RunLogContainer'

/**
 * Renders the report's linked tasks inline (latest status + purpose). Each row expands in place to
 * the task's run transcript via the shared `ReadonlyRunSurface` — live for an in-progress run, static
 * replay once terminal — mirroring the Code experience instead of navigating away to a separate run
 * page. Each row also links out to the run's page in Tasks for the full surface. The purpose label is
 * derived from each task's `task_run` artefact; `repo_selection` runs are filtered out.
 */
export function ReportTasksSection({ report }: { report: SignalReport }): JSX.Element | null {
    const { reportTasks, reportTasksLoading } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))

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
                    <TaskRow key={entry.task.id} entry={entry} reportId={report.id} report={report} />
                ))}
            </div>
        </DetailSection>
    )
}

function TaskRow({
    entry,
    reportId,
    report,
}: {
    entry: ReportTaskEntry
    reportId: string
    report: SignalReport
}): JSX.Element {
    const { task, purposeLabel } = entry
    const { expandedTaskIds } = useValues(inboxReportDetailLogic({ reportId, report }))
    const { toggleExpandedTask } = useActions(inboxReportDetailLogic({ reportId, report }))

    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    const runId = task.latest_run?.id ?? null
    const replayOnly = isTerminalRunStatus(task.latest_run?.status)
    const expanded = expandedTaskIds.includes(task.id)

    // Deep link to the run's own page in Tasks — the inline transcript is a preview, this is the
    // full surface (run history, composer). Falls back to the task when no run has started yet.
    const taskUrl = runId ? combineUrl(urls.taskDetail(task.id), { runId }).url : urls.taskDetail(task.id)

    return (
        <div>
            <div className="group flex w-full items-center gap-2 rounded px-1.5 py-1 text-xs transition-colors hover:bg-fill-highlight-50">
                <button
                    type="button"
                    onClick={() => toggleExpandedTask(task.id)}
                    className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                    {expanded ? (
                        <IconChevronDown className="shrink-0 text-tertiary" />
                    ) : (
                        <IconChevronRight className="shrink-0 text-tertiary" />
                    )}
                    <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                    <span className="truncate text-secondary">{purposeLabel}</span>
                </button>
                <Link
                    to={taskUrl}
                    aria-label={`Open ${purposeLabel} run in Tasks`}
                    title="Open run in Tasks"
                    // A 24px box keeps the tap target clear of the expand button on touch; the negative
                    // margin absorbs it back into the row so rows keep their height.
                    className="-my-1 flex size-6 shrink-0 items-center justify-center rounded text-tertiary opacity-60 transition-opacity hover:text-primary group-hover:opacity-100"
                >
                    <IconExternal className="size-3.5" />
                </Link>
            </div>

            {expanded ? (
                <div className="mt-1.5 mb-1 ml-1.5">
                    {runId ? (
                        // The viewer's virtualized thread owns scroll, so this box only bounds the height and
                        // clips — an `overflow-y-auto` here would nest a second scrollbar. Content is kept off
                        // the border via `threadRowClassName`/`threadListClassName`, not padding on this box.
                        <RunLogContainer>
                            <ReadonlyRunSurface
                                taskId={task.id}
                                runId={runId}
                                interaction={replayOnly ? 'read-only' : 'live'}
                                threadRowClassName="px-3"
                                threadListClassName="py-3"
                            />
                        </RunLogContainer>
                    ) : (
                        <div className="rounded border border-primary bg-surface-primary px-3 py-2.5 text-xs text-secondary leading-snug">
                            This run hasn't started yet. Its agent log will appear here once it does.
                        </div>
                    )}
                </div>
            ) : null}
        </div>
    )
}
