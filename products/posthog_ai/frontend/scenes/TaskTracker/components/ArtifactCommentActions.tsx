import { useActions, useValues } from 'kea'

import { IconPin } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactCommentsMenu } from './ArtifactCommentsMenu'

/** The toolbar controls for comments: the comments menu, and on an image, pin a comment to a spot. */
export function ArtifactCommentActions({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { pinMode } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setPinMode } = useActions(taskArtifactCommentsLogic(logicProps))
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
            <ArtifactCommentsMenu logicProps={logicProps} />
        </>
    )
}
