import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { useFileObjectUrl } from '../../hooks/useThreadAttachmentUrl'
import { type RunInteractionLogicProps, runInteractionLogic } from '../../logics/runInteractionLogic'
import { type PendingCommentContext, taskCommentContextsLogic } from '../../logics/taskCommentContextsLogic'
import { CommentContextChip } from '../CommentContextChip'

function ComposerCommentContextChip({
    context,
    onRemove,
}: {
    context: PendingCommentContext
    onRemove: () => void
}): JSX.Element {
    const screenshotUrl = useFileObjectUrl(context.screenshotFile)
    return <CommentContextChip context={context} screenshotUrl={screenshotUrl} onRemove={onRemove} />
}

export function CommentContextChips({ logicProps }: { logicProps: RunInteractionLogicProps }): JSX.Element | null {
    const { commentContexts, pendingCommentText } = useValues(taskCommentContextsLogic({ taskId: logicProps.taskId }))
    const { removeCommentContext } = useActions(taskCommentContextsLogic({ taskId: logicProps.taskId }))
    const { applyPendingCommentText, persistTaskDraft } = useActions(runInteractionLogic(logicProps))

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
                <ComposerCommentContextChip
                    key={context.id}
                    context={context}
                    onRemove={() => {
                        removeCommentContext(context.id)
                        persistTaskDraft()
                    }}
                />
            ))}
        </div>
    )
}
