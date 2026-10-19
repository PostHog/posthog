import { useActions, useValues } from 'kea'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactCommentComposer } from './ArtifactCommentComposer'

export function ArtifactReplyComposer({
    logicProps,
    rootId,
    rows,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    rootId: string
    rows: number
}): JSX.Element {
    const { writing, drafts } = useValues(taskArtifactCommentsLogic(logicProps))
    const { replyToThread, setDraft } = useActions(taskArtifactCommentsLogic(logicProps))
    return (
        <ArtifactCommentComposer
            value={drafts[rootId] ?? ''}
            onChange={(value) => setDraft(rootId, value)}
            onSubmit={(addToChat) => replyToThread(rootId, addToChat)}
            saving={writing === rootId}
            busy={!!writing && writing !== rootId}
            label="Reply"
            placeholder="Reply"
            submitLabel="Reply"
            rows={rows}
            dataAttr="task-artifact-comment-reply"
        />
    )
}
