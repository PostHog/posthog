import { useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FeedbackItem } from '../../models'
import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'

export function FeedbackList(): JSX.Element {
    const { feedbackItems, feedbackItemsLoading } = useValues(feedbackListSceneLogic)

    const columns: LemonTableColumns<FeedbackItem> = [
        {
            title: 'Feedback',
            key: 'content',
            render: (_, feedback) => (
                <div className="flex flex-col py-1">
                    <Link to={urls.feedbackItem(feedback.id)} className="font-semibold text-sm line-clamp-1">
                        {feedback.content}
                    </Link>
                    <div className="flex items-center gap-1.5 text-muted text-xs mt-1">
                        <span>Opened {dayjs(feedback.created_at).fromNow()}</span>
                        <span>·</span>
                        <span>todo@todo.com</span>
                        {feedback.assignment?.user && (
                            <>
                                <span>·</span>
                                <span>
                                    Assigned to {feedback.assignment.user.first_name}{' '}
                                    {feedback.assignment.user.last_name}
                                </span>
                            </>
                        )}
                        {feedback.attachments.length > 0 && (
                            <>
                                <span>·</span>
                                <span>
                                    {feedback.attachments.length} attachment
                                    {feedback.attachments.length !== 1 ? 's' : ''}
                                </span>
                            </>
                        )}
                    </div>
                </div>
            ),
        },
    ]

    return (
        <LemonTable
            dataSource={feedbackItems}
            columns={columns}
            loading={feedbackItemsLoading}
            rowKey="id"
            nouns={['feedback item', 'feedback items']}
            emptyState="No feedback items found"
        />
    )
}
