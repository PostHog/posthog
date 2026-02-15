import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

import { ActivityScope } from '~/types'

import { ParsedLogMessage } from 'products/logs/frontend/types'

export function LogComments({ log }: { log: ParsedLogMessage }): JSX.Element {
    const commentsLogicProps: CommentsLogicProps = {
        scope: ActivityScope.LOG,
        item_id: log.uuid,
        item_context: {
            log_timestamp: log.timestamp,
            service_name: log.resource_attributes?.service_name,
        },
    }

    return (
        <div className="flex flex-col gap-4">
            <CommentsList {...commentsLogicProps} noun="log" />
            <CommentComposer {...commentsLogicProps} />
        </div>
    )
}
