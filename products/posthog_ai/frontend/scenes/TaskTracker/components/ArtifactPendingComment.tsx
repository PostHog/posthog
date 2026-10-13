import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'

import { cn } from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactCommentComposer } from './ArtifactCommentComposer'

export const PENDING_COMMENT_WIDTH_PX = 288

/**
 * The box for a new comment on the pinned spot or the selected text. The caller places it, because a pin
 * and a selection measure their position in different ways.
 */
export function ArtifactPendingComment({
    logicProps,
    style,
    className,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    style: CSSProperties
    className?: string
}): JSX.Element | null {
    const { pendingAnchor, drafts, writing } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setDraft, submitComment, dismissPending } = useActions(taskArtifactCommentsLogic(logicProps))
    if (!pendingAnchor) {
        return null
    }
    const isText = pendingAnchor.kind === 'text'
    return (
        <div
            data-quill
            data-pending-artifact-comment
            className={cn(
                'absolute z-30 w-72 rounded-md border border-border bg-background p-2 text-left shadow-md',
                className
            )}
            style={style}
            // A press inside the box must not reach the image or the text below it.
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            data-attr="task-artifact-pending-comment"
        >
            <ArtifactCommentComposer
                autoFocus
                value={drafts.pending ?? ''}
                onChange={(value) => setDraft('pending', value)}
                onSubmit={() => submitComment('pending')}
                onCancel={dismissPending}
                saving={writing === 'pending'}
                busy={!!writing && writing !== 'pending'}
                quote={isText ? pendingAnchor.quote : undefined}
                label={isText ? 'Comment on the selected text' : 'Comment on this spot'}
                placeholder={isText ? 'Add a comment about this selection' : 'Add a comment about this spot'}
                rows={3}
                dataAttr={isText ? 'task-artifact-comment-selection' : 'task-artifact-comment-pin'}
            />
        </div>
    )
}
