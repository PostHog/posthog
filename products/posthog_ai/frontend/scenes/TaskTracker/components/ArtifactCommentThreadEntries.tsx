import { useActions, useValues } from 'kea'

import { IconCheck, IconRefresh } from '@posthog/icons'
import { ThreadItemAction, ThreadItemGroup } from '@posthog/quill-primitives'

import { ArtifactCommentThread } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactCommentEntry } from './ArtifactCommentEntry'

/** The comments in one thread, with the resolve or reopen action on the first comment. */
export function ArtifactCommentThreadEntries({
    logicProps,
    thread,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    thread: ArtifactCommentThread
}): JSX.Element {
    const { writing } = useValues(taskArtifactCommentsLogic(logicProps))
    const { setThreadResolved } = useActions(taskArtifactCommentsLogic(logicProps))
    const rootId = thread.root.id
    const resolveAction = (
        <ThreadItemAction
            label={thread.resolved ? 'Reopen thread' : 'Resolve thread'}
            variant="default"
            loading={writing === rootId}
            disabled={!!writing && writing !== rootId}
            onClick={() => setThreadResolved(rootId, !thread.resolved)}
            data-attr={thread.resolved ? 'task-artifact-comment-reopen' : 'task-artifact-comment-resolve'}
        >
            {thread.resolved ? <IconRefresh /> : <IconCheck />}
        </ThreadItemAction>
    )
    return (
        <ThreadItemGroup>
            <ArtifactCommentEntry comment={thread.root} actions={resolveAction} />
            {thread.replies.map((reply) => (
                <ArtifactCommentEntry key={reply.id} comment={reply} />
            ))}
        </ThreadItemGroup>
    )
}
