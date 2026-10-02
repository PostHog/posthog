import { useActions, useValues } from 'kea'

import { IconComment, IconPin } from '@posthog/icons'
import { Button, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { taskRunArtifactsLogic } from '../taskRunArtifactsLogic'

/** The toolbar controls for comments: show the panel, and on an image, pin a comment to a spot. */
export function ArtifactCommentActions({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { openCount, pinMode } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setPinMode } = useActions(taskArtifactCommentsLogic(logicProps))
    const { commentsOpen } = useValues(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const { setCommentsOpen } = useActions(taskRunArtifactsLogic({ taskId: logicProps.taskId }))
    const commentsLabel = commentsOpen ? 'Hide comments' : 'Show comments'
    const pinLabel = pinMode ? 'Stop pinning' : 'Pin a comment to a spot on the image'
    return (
        <>
            {logicProps.kind === 'image' && (
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            // Toggle cannot hold a ref, and the tooltip needs one to anchor, so this is a pressed Button.
                            <Button
                                size="icon"
                                aria-label={pinLabel}
                                aria-pressed={pinMode}
                                className={cn(pinMode && 'bg-fill-selected')}
                                onClick={() => setPinMode(!pinMode)}
                                data-attr="task-artifact-comment-pin-mode"
                            />
                        }
                    >
                        <IconPin />
                    </TooltipTrigger>
                    <TooltipContent>{pinLabel}</TooltipContent>
                </Tooltip>
            )}
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
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
        </>
    )
}
