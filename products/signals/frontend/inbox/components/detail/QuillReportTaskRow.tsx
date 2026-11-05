import { IconChevronDown, IconChevronRight, IconExternal } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReadonlyRunSurface } from 'products/posthog_ai/frontend/api/readableRun'

import type { ReportTaskEntry } from '../../logics/inboxReportDetailLogic'
import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { QuillRunLogContainer } from './QuillRunLogContainer'
import { useReportTaskRow } from './useReportTaskRow'

/**
 * The quill sibling of `ReportTaskRow`. The summary stays in a tooltip for the same reason: it runs to
 * paragraphs, which no row of this width can hold.
 */
export function QuillReportTaskRow({
    entry,
    expanded,
    onToggle,
}: {
    entry: ReportTaskEntry
    expanded: boolean
    onToggle: () => void
}): JSX.Element {
    const { task, purposeLabel } = entry
    const { status, runId, replayOnly, summary, taskUrl, captureSummaryViewed } = useReportTaskRow(entry)

    const expandButton = (
        <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
            {expanded ? (
                <IconChevronDown className="size-4 shrink-0 text-subtle-foreground" />
            ) : (
                <IconChevronRight className="size-4 shrink-0 text-subtle-foreground" />
            )}
            <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
            <Text
                size="xs"
                variant="muted"
                render={<span />}
                // pinned: data-attr value — autocapture and Playwright read it
                data-attr={summary ? 'report-run-summary' : undefined}
                className={cn('truncate', summary && 'border-b border-dotted border-current')}
            >
                {purposeLabel}
            </Text>
        </button>
    )

    return (
        <div>
            <div className="flex w-full items-center gap-2 rounded-md px-1.5 py-0.5 transition-colors hover:bg-fill-hover">
                {summary ? (
                    <Tooltip onOpenChange={(open) => open && captureSummaryViewed()}>
                        <TooltipTrigger render={expandButton} />
                        <TooltipContent side="bottom" align="start" className="max-w-80">
                            <span className="whitespace-pre-line">{summary}</span>
                        </TooltipContent>
                    </Tooltip>
                ) : (
                    expandButton
                )}
                <Button
                    size="icon-sm"
                    aria-label={`Open ${purposeLabel} run in Tasks`}
                    tooltip="Open run in Tasks"
                    render={<LinkPrimitive to={taskUrl} />}
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                >
                    <IconExternal />
                </Button>
            </div>

            {expanded ? <QuillRunTranscript taskId={task.id} runId={runId} replayOnly={replayOnly} /> : null}
        </div>
    )
}

function QuillRunTranscript({
    taskId,
    runId,
    replayOnly,
}: {
    taskId: string
    runId: string | null
    replayOnly: boolean
}): JSX.Element {
    return (
        <div className="mt-1.5 mb-1 ms-1.5">
            {runId ? (
                // The viewer's virtualized thread owns scroll, so the container only bounds the height
                // and clips. Content is kept off the border by the thread class names, not padding.
                <QuillRunLogContainer>
                    <ReadonlyRunSurface
                        taskId={taskId}
                        runId={runId}
                        interaction={replayOnly ? 'read-only' : 'live'}
                        threadRowClassName="px-3"
                        threadListClassName="py-3"
                    />
                </QuillRunLogContainer>
            ) : (
                <div className="rounded-md border border-border bg-card px-3 py-2.5">
                    <Text size="xs" variant="muted" className="m-0 leading-snug">
                        This run hasn't started yet. Its agent log will appear here once it does.
                    </Text>
                </div>
            )}
        </div>
    )
}
