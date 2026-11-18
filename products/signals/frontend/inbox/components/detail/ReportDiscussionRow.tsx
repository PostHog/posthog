import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'

import { isTerminalRunStatus } from 'products/posthog_ai/frontend/api/logics'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import type { ReportDiscussion } from '../../logics/inboxReportDetailLogic'
import { resolveRunVariant, RunStatusIndicator } from '../cards/runStatusVariant'
import { ReportRunTranscript } from './ReportRunTranscript'

/**
 * One Ask AI chat on a report: who asked, what they asked, and the first line of the answer. It
 * expands in place to the full answer. A chat with no answer yet expands to its transcript instead,
 * so a reader can follow a run that is still working.
 */
export function ReportDiscussionRow({
    discussion,
    expanded,
    onToggle,
    onOpenChat,
}: {
    discussion: ReportDiscussion
    expanded: boolean
    onToggle: () => void
    onOpenChat: (runId: string) => void
}): JSX.Element {
    const { entry, question } = discussion
    const { task } = entry
    const status = task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
    const runId = task.latest_run?.id ?? null
    const terminal = isTerminalRunStatus(task.latest_run?.status)
    const summary = task.latest_run?.task_summary?.trim() || null
    const asker = task.created_by?.first_name?.trim() || task.created_by?.email || 'Someone'
    const preview = summary
        ? summary.split('\n').find((line) => line.trim())
        : !terminal
          ? 'Working on an answer'
          : status === TaskRunStatus.FAILED
            ? 'The run stopped before it answered.'
            : null

    return (
        <div className="flex gap-2.5 border-b border-primary px-3 py-2.5 last:border-b-0">
            <ProfilePicture user={task.created_by ?? { first_name: asker }} size="md" />
            <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="font-medium text-default">{asker}</span>
                    <span className="text-tertiary">asked PostHog AI</span>
                    <TZLabel time={entry.startedAt} className="text-tertiary" />
                </div>
                <button
                    type="button"
                    onClick={onToggle}
                    aria-expanded={expanded}
                    // pinned: data-attr value, autocapture reads it
                    data-attr="report-discussion-row"
                    className="mt-1 flex w-full items-start gap-2 rounded text-left"
                >
                    <span className="min-w-0 flex-1">
                        <span
                            className={cn(
                                'block whitespace-pre-line break-words text-sm text-default',
                                !expanded && 'line-clamp-2'
                            )}
                        >
                            {question || task.title}
                        </span>
                        {!expanded && preview ? (
                            <span className="mt-0.5 block truncate text-xs text-secondary">{preview}</span>
                        ) : null}
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5 pt-0.5 text-tertiary">
                        <RunStatusIndicator variant={resolveRunVariant(status)} showLabel={false} />
                        {expanded ? <IconChevronDown /> : <IconChevronRight />}
                    </span>
                </button>
                {expanded ? (
                    <div className="mt-2 flex flex-col gap-2">
                        {summary ? (
                            <LemonMarkdown className="text-sm text-default" disableImages>
                                {summary}
                            </LemonMarkdown>
                        ) : (
                            <ReportRunTranscript taskId={task.id} runId={runId} replayOnly={terminal} />
                        )}
                        {runId ? (
                            <div className="flex flex-wrap gap-2">
                                <LemonButton size="small" type="secondary" onClick={() => onOpenChat(runId)}>
                                    Open chat
                                </LemonButton>
                            </div>
                        ) : null}
                    </div>
                ) : null}
            </div>
        </div>
    )
}
