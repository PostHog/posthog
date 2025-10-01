import { LemonTag } from '@posthog/lemon-ui'

import { FeedbackItem, FeedbackType } from '../../types'

export interface FeedbackListItemProps {
    feedback: FeedbackItem
}

const TYPE_COLORS: Record<FeedbackType, 'primary' | 'danger' | 'default'> = {
    [FeedbackType.Bug]: 'danger',
    [FeedbackType.Feedback]: 'primary',
    [FeedbackType.Question]: 'default',
}

const TYPE_LABELS: Record<FeedbackType, string> = {
    [FeedbackType.Bug]: 'Bug',
    [FeedbackType.Feedback]: 'Feedback',
    [FeedbackType.Question]: 'Question',
}

export function FeedbackListItem({ feedback }: FeedbackListItemProps): JSX.Element {
    return (
        <div className="border-b last:border-b-0 p-4 hover:bg-surface-secondary transition-colors">
            <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                        <span className="font-medium text-sm">{feedback.user}</span>
                        <span className="text-muted text-xs">·</span>
                        <span className="text-muted text-xs">{feedback.timestamp}</span>
                    </div>
                    <p className="text-base mb-3">{feedback.message}</p>
                    <LemonTag type={TYPE_COLORS[feedback.type]}>{TYPE_LABELS[feedback.type]}</LemonTag>
                </div>
            </div>
        </div>
    )
}
