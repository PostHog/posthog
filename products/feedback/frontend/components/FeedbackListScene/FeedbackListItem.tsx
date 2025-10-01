import { useActions } from 'kea'

import { LemonBadge, LemonTag } from '@posthog/lemon-ui'

import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'
import { FeedbackItem, FeedbackStatus } from '../../types'

export interface FeedbackListItemProps {
    feedback: FeedbackItem
}

const STATUS_CONFIG: Record<FeedbackStatus, { label: string; color: 'success' | 'warning' }> = {
    [FeedbackStatus.Visible]: { label: 'Visible', color: 'success' },
    [FeedbackStatus.Hidden]: { label: 'Hidden', color: 'warning' },
}

export function FeedbackListItem({ feedback }: FeedbackListItemProps): JSX.Element {
    const { openFeedbackItem } = useActions(feedbackListSceneLogic)
    const truncatedTopic = feedback.topic.length > 50 ? `${feedback.topic.slice(0, 50)}...` : feedback.topic

    return (
        <div
            className="border-b last:border-b-0 p-4 hover:bg-surface-secondary transition-colors cursor-pointer"
            onClick={() => openFeedbackItem(feedback.id)}
        >
            <div className="flex items-center justify-between">
                <div className="flex-1">
                    <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{feedback.user}</span>
                        <span className="text-muted text-xs">·</span>
                        <span className="text-muted text-xs">{feedback.timestamp}</span>
                        <span className="text-muted text-xs">·</span>
                        <LemonTag>
                            <span className="capitalize">{feedback.category}</span>
                        </LemonTag>
                        <span className="text-muted text-xs">·</span>
                        <span className="text-muted text-xs">{truncatedTopic}</span>
                    </div>
                    <p className="text-sm m-0">{feedback.message}</p>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                    <LemonBadge status={STATUS_CONFIG[feedback.status].color} size="small" />
                    <span className="text-xs text-muted">{STATUS_CONFIG[feedback.status].label}</span>
                </div>
            </div>
        </div>
    )
}
