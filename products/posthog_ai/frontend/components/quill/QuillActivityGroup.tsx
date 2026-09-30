import { IconWrench } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { ActivityElapsedTime } from '../ActivityElapsedTime'
import { ActivityGroupRows } from '../ActivityGroupRows'
import { type ActivityGroupProps, useActivityGroup } from '../useActivityGroup'
import { ThreadMarker } from './ThreadMarker'

export function QuillActivityGroup(props: ActivityGroupProps): JSX.Element {
    const { group, toolInvocations, active, waitingForInput = false, renderItem } = props
    const {
        label,
        currentLabel,
        calls,
        thoughtsOnly,
        expanded,
        setExpanded,
        window,
        showMiddle,
        toggleMiddle,
        visibleThoughtsOnly,
        newCount,
        showNew,
    } = useActivityGroup(props)
    const rowProps = { thoughtsOnly: visibleThoughtsOnly, toolInvocations, active, renderItem }
    const running = active && !waitingForInput

    return (
        <ThreadMarker
            icon={<IconWrench />}
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
            <span className="shrink-0 font-medium" data-attr="thread-activity-toggle">
                {running && !thoughtsOnly ? currentLabel : label}
            </span>
            {waitingForInput && <span className="truncate">Review the request below</span>}
            {!waitingForInput && (
                <ActivityElapsedTime startedAt={group.startedAt} endedAt={group.endedAt} active={active} />
            )}
            {calls.length > 0 && (
                <span className="shrink-0 tabular-nums">
                    · {calls.length} tool {calls.length === 1 ? 'call' : 'calls'}
                </span>
            )}
        </ThreadMarker>
    )
}
