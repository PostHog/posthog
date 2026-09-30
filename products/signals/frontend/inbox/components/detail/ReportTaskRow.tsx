import { combineUrl } from 'kea-router'
import { useCallback } from 'react'

import { IconChevronDown, IconChevronRight, IconExternal } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { captureInboxRunSummaryViewed } from '../../inboxAnalytics'
import type { ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { RunLogContainer } from './RunLogContainer'

/**
 * One row of a report's Runs list: the run's status, its purpose label, and — on hover or keyboard
 * focus — the summary the agent wrote for itself. The row expands in place to the run transcript via
 * the shared `ReadonlyRunSurface` (live while the run works, static replay once terminal), and links
 * out to the run's page in Tasks for the full surface.
 *
 * The summary sits in a tooltip rather than in the row because it runs to paragraphs, which no row
 * of this width can hold. A run that wrote none keeps a plain label, so the dotted underline reads
 * as "there is more here".
 */
export function ReportTaskRow({
    entry,
    expanded,
    onToggle,
}: {
    entry: ReportTaskEntry
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    const { task, purpose, purposeLabel } = entry

    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    const runId = task.latest_run?.id ?? null
    const replayOnly = isTerminalRunStatus(task.latest_run?.status)
    const summary = task.latest_run?.task_summary?.trim() || null

    const captureSummaryViewed = useCallback(
        () => captureInboxRunSummaryViewed({ purpose, status, summaryLength: summary?.length ?? 0 }),
        [purpose, status, summary]
    )

    // Deep link to the run's own page in Tasks — the inline transcript is a preview, this is the
    // full surface (run history, composer). Falls back to the task when no run has started yet.
    const taskUrl = runId ? combineUrl(urls.taskDetail(task.id), { runId }).url : urls.taskDetail(task.id)

    const expandButton = (
        <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
            {expanded ? (
                <IconChevronDown className="shrink-0 text-tertiary" />
            ) : (
                <IconChevronRight className="shrink-0 text-tertiary" />
            )}
            <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
            <span
                // pinned: data-attr value — autocapture and Playwright read it
                data-attr={summary ? 'report-run-summary' : undefined}
                className={cn('truncate text-secondary', summary && 'border-b border-dotted')}
            >
                {purposeLabel}
            </span>
        </button>
    )

    return (
        <div>
            <div className="group flex w-full items-center gap-2 rounded px-1.5 py-1 text-xs transition-colors hover:bg-fill-highlight-50">
                {summary ? (
                    <Tooltip
                        title={<span className="whitespace-pre-line">{summary}</span>}
                        placement="bottom-start"
                        onOpen={captureSummaryViewed}
                    >
                        {expandButton}
                    </Tooltip>
                ) : (
                    expandButton
                )}
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

            {expanded ? <RunTranscript taskId={task.id} runId={runId} replayOnly={replayOnly} /> : null}
        </div>
    )
}

function RunTranscript({
    taskId,
    runId,
    replayOnly,
}: {
    taskId: string
    runId: string | null
    replayOnly: boolean
}): JSX.Element {
    return (
        <div className="mt-1.5 mb-1 ml-1.5">
            {runId ? (
                // The viewer's virtualized thread owns scroll, so this box only bounds the height and
                // clips — an `overflow-y-auto` here would nest a second scrollbar. Content is kept off
                // the border via `threadRowClassName`/`threadListClassName`, not padding on this box.
                <RunLogContainer>
                    <ReadonlyRunSurface
                        taskId={taskId}
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
    )
}
