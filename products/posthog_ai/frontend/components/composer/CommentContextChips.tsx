import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { type RunInteractionLogicProps, runInteractionLogic } from '../../logics/runInteractionLogic'
import { taskCommentContextsLogic } from '../../logics/taskCommentContextsLogic'
import { CommentContextChip } from '../CommentContextChip'

export function CommentContextChips({ logicProps }: { logicProps: RunInteractionLogicProps }): JSX.Element | null {
    const { commentContexts, pendingCommentText } = useValues(taskCommentContextsLogic({ taskId: logicProps.taskId }))
    const { removeCommentContext } = useActions(taskCommentContextsLogic({ taskId: logicProps.taskId }))
    const { applyPendingCommentText } = useActions(runInteractionLogic(logicProps))

    useEffect(() => {
        if (pendingCommentText.length > 0) {
            applyPendingCommentText()
        }
    }, [pendingCommentText, applyPendingCommentText])

    if (commentContexts.length === 0) {
        return null
    }
    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1">
            {commentContexts.map((context) => (
                <CommentContextChip
                    key={context.id}
                    context={context}
                    onRemove={() => removeCommentContext(context.id)}
                />
            ))}
        </div>
    )
}
