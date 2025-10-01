import { LemonTag } from '@posthog/lemon-ui'

import { FeedbackItem } from '../../types'

export interface FeedbackListItemProps {
    feedback: FeedbackItem
}

export function FeedbackListItem({ feedback }: FeedbackListItemProps): JSX.Element {
    const getTypeColor = (): 'primary' | 'danger' | 'default' => {
        switch (feedback.type) {
            case 'bug':
                return 'danger'
            case 'feature request':
                return 'primary'
            default:
                return 'default'
        }
    }

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
                    <LemonTag type={getTypeColor()} className="capitalize">
                        {feedback.type}
                    </LemonTag>
                </div>
            </div>
        </div>
    )
}
