import { useActions } from 'kea'

import { LemonBadge, LemonTag } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { FeedbackItem } from '../../models'
import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'

export interface FeedbackListItemProps {
    feedback: FeedbackItem
}

export function FeedbackListItem({ feedback }: FeedbackListItemProps): JSX.Element {
    const { openFeedbackItem } = useActions(feedbackListSceneLogic)
    const truncatedTopic =
        feedback.topic?.name?.length && feedback.topic?.name.length > 50
            ? `${feedback.topic.name.slice(0, 50)}...`
            : feedback.topic?.name

    return (
        <div
            className="border-b last:border-b-0 p-4 hover:bg-surface-secondary transition-colors cursor-pointer"
            onClick={() => openFeedbackItem(feedback.id)}
        >
            <div className="flex items-center justify-between">
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">todo@todo.com</span>
                        <span className="text-muted text-xs">·</span>
                        <span className="text-muted text-xs">{dayjs(feedback.created_at).fromNow()}</span>
                        <span className="text-muted text-xs">·</span>
                        <LemonTag>
                            <span className="capitalize">{feedback.category?.name}</span>
                        </LemonTag>
                        <span className="text-muted text-xs">·</span>
                        <span className="text-muted text-xs">{truncatedTopic}</span>
                    </div>
                    <p className="text-sm m-0">{feedback.content}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                    <LemonBadge status="success" size="small" />
                    <span className="text-xs text-muted">{feedback.status?.name}</span>
                </div>
            </div>
        </div>
    )
}
