import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'

export interface FeedbackDiscussionsProps {
    feedbackItemId: string
}

export function FeedbackDiscussions({ feedbackItemId }: FeedbackDiscussionsProps): JSX.Element {
    return (
        <div className="border rounded-lg overflow-hidden bg-surface">
            <div className="border-b p-4 bg-surface-secondary">
                <h3 className="text-base font-semibold m-0">Discussion</h3>
            </div>
            <div className="p-4">
                <CommentsList scope="feedback" item_id={feedbackItemId} />
                <div className="mt-4">
                    <CommentComposer scope="feedback" item_id={feedbackItemId} />
                </div>
            </div>
        </div>
    )
}
