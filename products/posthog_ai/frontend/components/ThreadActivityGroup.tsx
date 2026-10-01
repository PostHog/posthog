import { IconChevronRight, IconSpinner } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ActivityDisclosure } from './ActivityDisclosure'
import { ActivityElapsedTime } from './ActivityElapsedTime'
import { ActivityGroupRows } from './ActivityGroupRows'
import { QuillActivityGroup } from './quill/QuillActivityGroup'
import { useQuillThread } from './quill/quillThreadContext'
import { type ActivityGroupProps, useActivityGroup } from './useActivityGroup'

export function ThreadActivityGroup(props: ActivityGroupProps): JSX.Element {
    return useQuillThread() ? <QuillActivityGroup {...props} /> : <LemonThreadActivityGroup {...props} />
}

function LemonThreadActivityGroup(props: ActivityGroupProps): JSX.Element {
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

    return (
        <div
            className="flex flex-col gap-1 min-w-0 text-[13px] leading-5 font-normal"
            data-attr="thread-activity-group"
        >
            <LemonButton
                type="tertiary"
                size="small"
                fullWidth
                onClick={() => setExpanded(!expanded)}
                aria-expanded={expanded}
                aria-controls={`activity-details-${group.id}`}
                data-attr="thread-activity-toggle"
                icon={
                    <span className="flex size-5 items-center justify-center">
                        <IconChevronRight
                            className={`text-[13px] transition-transform duration-150 ease-out motion-reduce:transition-none ${expanded ? 'rotate-90' : ''}`}
                        />
                    </span>
                }
            >
                <span className="flex items-center gap-2 flex-wrap min-w-0 text-[13px] leading-5 font-normal">
                    <span>{label}</span>
                    {active && !waitingForInput && <IconSpinner className="animate-spin motion-reduce:animate-none" />}
                    {!waitingForInput && (
                        <ActivityElapsedTime startedAt={group.startedAt} endedAt={group.endedAt} active={active} />
                    )}
                    {calls.length > 0 && (
                        <span
                            className="text-muted tabular-nums"
                            title="Tool calls in this activity group, not the whole response. Calls shown separately are not included."
                        >
                            ·{' '}
                            <span
                                key={calls.length}
                                className="inline-block animate-fade-in [animation-duration:150ms] motion-reduce:animate-none"
                            >
                                {calls.length}
                            </span>{' '}
                            tool {calls.length === 1 ? 'call' : 'calls'}
                        </span>
                    )}
                </span>
            </LemonButton>
            {active && (!thoughtsOnly || waitingForInput) && (
                <div className="pl-9 text-muted truncate h-5" title={currentLabel}>
                    {waitingForInput ? 'Review the request below' : currentLabel}
                </div>
            )}
            <ActivityDisclosure open={expanded} id={`activity-details-${group.id}`}>
                <div className="ml-3 pl-3 border-l border-border-secondary flex flex-col gap-1 min-w-0">
                    <ActivityGroupRows items={window.first} fold={false} {...rowProps} />
                    {window.hiddenCount > 0 && (
                        <>
                            <LemonButton
                                type="tertiary"
                                size="xsmall"
                                data-attr="thread-activity-more"
                                aria-expanded={showMiddle}
                                aria-controls={`activity-middle-${group.id}`}
                                onClick={toggleMiddle}
                            >
                                {showMiddle ? 'Show less' : `Show ${window.hiddenCount} more`}
                            </LemonButton>
                            <ActivityDisclosure open={showMiddle} id={`activity-middle-${group.id}`}>
                                <div className="flex flex-col gap-1 min-w-0">
                                    <ActivityGroupRows items={window.middle} fold {...rowProps} />
                                </div>
                            </ActivityDisclosure>
                        </>
                    )}
                    <ActivityGroupRows items={window.last} fold={false} {...rowProps} />
                    {newCount > 0 && (
                        <LemonButton
                            type="tertiary"
                            size="xsmall"
                            data-attr="thread-activity-refresh"
                            onClick={showNew}
                        >
                            Show {newCount} new {newCount === 1 ? 'activity' : 'activities'}
                        </LemonButton>
                    )}
                </div>
            </ActivityDisclosure>
        </div>
    )
}
