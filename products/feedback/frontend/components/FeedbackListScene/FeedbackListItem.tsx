import { useActions } from 'kea'

import { IconBug, IconQuestion } from '@posthog/icons'
import { LemonBadge, LemonTag } from '@posthog/lemon-ui'

import { IconFeedback } from '~/lib/lemon-ui/icons'

import { feedbackListSceneLogic } from '../../scenes/FeedbackListScene/feedbackListSceneLogic'
import { FeedbackItem, FeedbackStatus, FeedbackType } from '../../types'

export interface FeedbackListItemProps {
    feedback: FeedbackItem
}

const TYPE_COLORS: Record<FeedbackType, 'primary' | 'danger' | 'default'> = {
    [FeedbackType.Bug]: 'danger',
    [FeedbackType.Feedback]: 'primary',
    [FeedbackType.Question]: 'default',
}

const TYPE_CONFIG: Record<FeedbackType, { label: string; icon: JSX.Element }> = {
    [FeedbackType.Bug]: { label: 'Bug', icon: <IconBug /> },
    [FeedbackType.Feedback]: { label: 'Feedback', icon: <IconFeedback /> },
    [FeedbackType.Question]: { label: 'Question', icon: <IconQuestion /> },
}

const STATUS_CONFIG: Record<FeedbackStatus, { label: string; color: 'success' | 'warning' }> = {
    [FeedbackStatus.Visible]: { label: 'Visible', color: 'success' },
    [FeedbackStatus.Hidden]: { label: 'Hidden', color: 'warning' },
}

export function FeedbackListItem({ feedback }: FeedbackListItemProps): JSX.Element {
    const { openFeedbackItem } = useActions(feedbackListSceneLogic)

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
                        <LemonTag type={TYPE_COLORS[feedback.type]} icon={TYPE_CONFIG[feedback.type].icon}>
                            {TYPE_CONFIG[feedback.type].label}
                        </LemonTag>
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
