import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FeedbackItem } from '../../models'
import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'

export function FeedbackList(): JSX.Element {
    const { feedbackItems, feedbackItemsLoading } = useValues(feedbackListSceneLogic)
    const { feedbackCategories, feedbackTopics, feedbackStatuses } = useValues(feedbackGeneralSettingsLogic)
    const { initializeDefaultData } = useActions(feedbackGeneralSettingsLogic)

    const shouldShowWizard =
        feedbackCategories.length === 0 &&
        feedbackTopics.length === 0 &&
        feedbackStatuses.length === 0 &&
        feedbackItems.length === 0 &&
        !feedbackItemsLoading

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

    if (shouldShowWizard) {
        return (
            <div className="flex flex-col items-center justify-center py-16 gap-4">
                <div className="text-center">
                    <h3 className="text-lg font-semibold mb-2">Get started with feedback</h3>
                    <p className="text-muted">
                        Set up default categories, topics, and statuses to start organizing feedback
                    </p>
                </div>
                <LemonButton type="primary" icon={<IconPlus />} size="large" onClick={() => initializeDefaultData()}>
                    Initialize feedback system
                </LemonButton>
            </div>
        )
    }

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
