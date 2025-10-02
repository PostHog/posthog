import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'

export function FeedbackSummary(): JSX.Element {
    const { feedbackItem, feedbackItemLoading } = useValues(feedbackItemSceneLogic)
    const { feedbackStatuses } = useValues(feedbackGeneralSettingsLogic)
    const { updateStatus, updateAssignment } = useActions(feedbackItemSceneLogic)

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
                <div className="grid grid-cols-3 gap-6 mb-4">
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
                <div className="grid grid-cols-2 gap-6">
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Status</h4>
                        <LemonSelect
                            value={feedbackItem.status?.id}
                            onChange={(value) => value && updateStatus(value)}
                            options={feedbackStatuses.map((status) => ({
                                label: status.name,
                                value: status.id,
                            }))}
                            size="small"
                        />
                    </div>
                    <div>
                        <h4 className="text-xs font-semibold text-muted mb-1">Assigned to</h4>
                        <MemberSelect
                            value={feedbackItem.assignment?.user?.id ?? null}
                            onChange={(user) => updateAssignment(user?.id ?? null)}
                            defaultLabel="Unassigned"
                            allowNone={true}
                            type="secondary"
                            size="small"
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
