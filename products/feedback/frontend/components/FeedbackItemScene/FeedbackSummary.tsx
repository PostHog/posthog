import { useValues } from 'kea'

import { LemonBadge, LemonTag } from '@posthog/lemon-ui'

import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'

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
                            <LemonBadge status="success" size="small" />
                            <span className="text-xs text-muted">{feedbackItem.status?.name}</span>
                        </div>
                    </div>
                </div>

                <div className="space-y-2">
                    <div className="flex items-center gap-2">
                        <span className="font-semibold text-base">todo@todo.com</span>
                        <span className="text-muted text-sm">·</span>
                        <span className="text-muted text-sm">{feedbackItem.created_at}</span>
                    </div>
                </div>
            </div>

            <div className="p-6">
                <h3 className="text-sm font-semibold text-muted mb-2">Message</h3>
                <p className="text-base m-0 whitespace-pre-wrap">{feedbackItem.content}</p>
            </div>

            <div className="border-t p-6 bg-surface-secondary">
                <div className="grid grid-cols-3 gap-6">
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Feedback ID</h4>
                        <p className="text-sm m-0 font-mono">{feedbackItem.id}</p>
                    </div>
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Category</h4>
                        <p className="text-sm m-0 capitalize">{feedbackItem.category?.name}</p>
                    </div>
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Topic</h4>
                        <p className="text-sm m-0">{feedbackItem.topic?.name}</p>
                    </div>
                </div>
            </div>
        </div>
    )
}
