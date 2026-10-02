import { useActions, useValues } from 'kea'

import { IconComment } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'

/** The toolbar control for comments: show or hide the panel. */
export function ArtifactCommentActions({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { openCount } = useValues(taskArtifactCommentsLogic(logicProps))
    const { commentsOpen } = useValues(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const commentsLabel = commentsOpen ? 'Hide comments' : 'Show comments'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    // Toggle cannot hold a ref, and the tooltip needs one to anchor, so this is a pressed Button.
                    <Button
                        aria-label={openCount > 0 ? `${commentsLabel}, ${openCount} open` : commentsLabel}
                        aria-pressed={commentsOpen}
                        className={cn(commentsOpen && 'bg-fill-selected')}
                        onClick={() => setCommentsOpen(!commentsOpen)}
                        data-attr="task-artifact-comments-toggle"
                    />
                }
            >
                <IconComment />
                {openCount > 0 && (
                    <Text size="xs" render={<span />} className="tabular-nums">
                        {openCount}
                    </Text>
                )}
            </TooltipTrigger>
            <TooltipContent>{commentsLabel}</TooltipContent>
        </Tooltip>
    )
}
