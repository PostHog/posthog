import { IconWrench } from '@posthog/icons'
import { Button, cn } from '@posthog/quill-primitives'

import type { ToolInvocation } from '../../types/streamTypes'
import { resolveToolCall } from '../../utils/toolResolver'
import { summarizeToolRun } from '../../utils/toolRunSummary'
import { ActivityGroupRows } from '../ActivityGroupRows'
import { lookupToolRenderer } from '../tool/toolRegistry'
import { type ActivityGroupProps, useActivityGroup } from '../useActivityGroup'
import { ThreadMarker } from './ThreadMarker'

function describeCall(call: ToolInvocation): { name: string; detail?: string; icon: JSX.Element } {
    const resolved = resolveToolCall(call)
    const { displayName, icon } = lookupToolRenderer(resolved.resolvedKey, !!resolved.innerToolName)
    // The PostHog MCP asks the agent for a one-sentence `context` on every call, and its `exec` title says nothing.
    const intent = typeof call.input.context === 'string' ? call.input.context.trim() : ''
    if (intent || resolved.innerToolName || !call.title) {
        return { name: displayName, detail: intent || undefined, icon }
    }
    // A title such as "Read digest/scheduler.py" already names the tool.
    if (call.title.toLowerCase().startsWith(displayName.toLowerCase())) {
        return { name: call.title, icon }
    }
    return { name: displayName, detail: call.title, icon }
}

const isRunning = (call: ToolInvocation): boolean => call.status === 'pending' || call.status === 'in_progress'

export function QuillActivityGroup(props: ActivityGroupProps): JSX.Element {
    const { group, toolInvocations, active, cancelled, waitingForInput = false, renderItem } = props
    const { calls, expanded, setExpanded, window, showMiddle, toggleMiddle, visibleThoughtsOnly, newCount, showNew } =
        useActivityGroup(props)
    const rowProps = { thoughtsOnly: visibleThoughtsOnly, toolInvocations, active, renderItem }
    const running = active && !waitingForInput
    const thinking = running && group.items.at(-1)?.type === 'assistant_thought'
    const current = calls.findLast(isRunning) ?? calls.at(-1)
    const lead = current ? describeCall(current) : undefined
    const failedCount = calls.filter((call) => call.status === 'failed').length

    return (
        <ThreadMarker
            icon={lead?.icon ?? <IconWrench />}
            running={running}
            spinner
            open={expanded}
            onOpenChange={setExpanded}
            body={
                <div className="flex min-w-0 flex-col gap-1" data-attr="thread-activity-group">
                    <ActivityGroupRows items={window.first} fold={false} {...rowProps} />
                    {window.hiddenCount > 0 && (
                        <Button
                            variant="link-muted"
                            size="xs"
                            className="self-start"
                            data-attr="thread-activity-more"
                            aria-expanded={showMiddle}
                            onClick={toggleMiddle}
                        >
                            {showMiddle ? 'Show less' : `Show ${window.hiddenCount} more`}
                        </Button>
                    )}
                    <ActivityGroupRows items={window.middle} fold {...rowProps} />
                    <ActivityGroupRows items={window.last} fold={false} {...rowProps} />
                    {newCount > 0 && (
                        <Button
                            variant="link-muted"
                            size="xs"
                            className="self-start"
                            data-attr="thread-activity-refresh"
                            onClick={showNew}
                        >
                            Show {newCount} new {newCount === 1 ? 'activity' : 'activities'}
                        </Button>
                    )}
                </div>
            }
        >
            {waitingForInput ? (
                <>
                    <span className="shrink-0 font-medium" data-attr="thread-activity-toggle">
                        Waiting for you
                    </span>
                    <span className="truncate">Review the request below</span>
                </>
            ) : running ? (
                <>
                    <span
                        className={cn('truncate font-medium', !thinking && lead?.detail ? 'shrink-0' : 'min-w-0')}
                        data-attr="thread-activity-toggle"
                    >
                        {thinking || !lead ? 'Thinking…' : lead.name}
                    </span>
                    {!thinking && lead?.detail && <span className="truncate opacity-70">{lead.detail}</span>}
                </>
            ) : (
                <>
                    {/* A collapsed group still has to say the run stopped, or that a call in it failed. */}
                    {cancelled && <span className="shrink-0 font-medium">Stopped</span>}
                    <span className="truncate" data-attr="thread-activity-toggle">
                        {summarizeToolRun(calls)}
                    </span>
                    {failedCount > 0 && (
                        <span className="shrink-0 text-(--destructive-foreground)">{failedCount} failed</span>
                    )}
                </>
            )}
        </ThreadMarker>
    )
}
