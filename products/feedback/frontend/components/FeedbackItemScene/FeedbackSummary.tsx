import { useValues } from 'kea'

import { LemonBadge, LemonTag } from '@posthog/lemon-ui'

import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'
import { FeedbackStatus } from '../../types'

const STATUS_CONFIG: Record<FeedbackStatus, { label: string; color: 'success' | 'warning' }> = {
    [FeedbackStatus.Visible]: { label: 'Visible', color: 'success' },
    [FeedbackStatus.Hidden]: { label: 'Hidden', color: 'warning' },
}

export function FeedbackSummary(): JSX.Element {
    const { feedbackItem, feedbackItemLoading } = useValues(feedbackItemSceneLogic)

    if (feedbackItemLoading) {
        return (
            <div className="border rounded-lg p-6 bg-surface">
                <p className="text-muted m-0">Loading</p>
            </div>
        )
    }

    if (!feedbackItem) {
        return (
            <div className="border rounded-lg p-6 bg-surface">
                <p className="text-muted m-0">Feedback item not found</p>
            </div>
        )
    }

    return (
        <div className="border rounded-lg overflow-hidden bg-surface">
            <div className="border-b p-6 bg-surface-secondary">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <LemonTag>
                            <span className="capitalize">{feedbackItem.category}</span>
                        </LemonTag>
                        <div className="flex items-center gap-1.5">
                            <LemonBadge status={STATUS_CONFIG[feedbackItem.status].color} size="small" />
                            <span className="text-xs text-muted">{STATUS_CONFIG[feedbackItem.status].label}</span>
                        </div>
                    </div>
                </div>

                <div className="space-y-2">
                    <div className="flex items-center gap-2">
                        <span className="font-semibold text-base">{feedbackItem.user}</span>
                        <span className="text-muted text-sm">·</span>
                        <span className="text-muted text-sm">{feedbackItem.timestamp}</span>
                    </div>
                </div>
            </div>

            <div className="p-6">
                <h3 className="text-sm font-semibold text-muted mb-2">Message</h3>
                <p className="text-base m-0 whitespace-pre-wrap">{feedbackItem.message}</p>
            </div>

            <div className="border-t p-6 bg-surface-secondary">
                <div className="grid grid-cols-3 gap-6">
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Feedback ID</h4>
                        <p className="text-sm m-0 font-mono">{feedbackItem.id}</p>
                    </div>
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Category</h4>
                        <p className="text-sm m-0 capitalize">{feedbackItem.category}</p>
                    </div>
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Topic</h4>
                        <p className="text-sm m-0">{feedbackItem.topic}</p>
                    </div>
                </div>
            </div>
        </div>
    )
}
