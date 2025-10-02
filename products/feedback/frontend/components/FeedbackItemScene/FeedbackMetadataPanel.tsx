import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'

export function FeedbackMetadataPanel(): JSX.Element {
    const { feedbackItem, feedbackItemLoading } = useValues(feedbackItemSceneLogic)
    const { feedbackCategories, feedbackTopics, getStatusesForCategory } = useValues(feedbackGeneralSettingsLogic)
    const { updateStatus, updateAssignment, updateCategory, updateTopic } = useActions(feedbackItemSceneLogic)

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
            <div className="border-b p-4 bg-surface-secondary">
                <h3 className="text-sm font-semibold m-0">Details</h3>
            </div>

            <div className="divide-y">
                <MetadataRow title="Feedback ID" value={feedbackItem.id} valueClassName="font-mono text-xs" />

                <MetadataRow title="Created At" value={feedbackItem.created_at} />

                <MetadataRow title="Email" value="todo@todo.com" />

                <MetadataRow
                    title="Category"
                    value={
                        <LemonSelect
                            value={feedbackItem.category?.id}
                            onChange={(value) => value && updateCategory(value)}
                            options={feedbackCategories.map((category) => ({
                                label: category.name,
                                value: category.id,
                            }))}
                            size="small"
                            placeholder="Select category"
                        />
                    }
                />

                <MetadataRow
                    title="Status"
                    value={
                        <LemonSelect
                            value={feedbackItem.status?.id}
                            onChange={(value) => value && updateStatus(value)}
                            options={
                                feedbackItem.category?.id
                                    ? getStatusesForCategory(feedbackItem.category.id).map((status) => ({
                                          label: status.name,
                                          value: status.id,
                                      }))
                                    : []
                            }
                            size="small"
                            placeholder="Select status"
                            disabled={!feedbackItem.category}
                        />
                    }
                />

                <MetadataRow
                    title="Topic"
                    value={
                        <LemonSelect
                            value={feedbackItem.topic?.id}
                            onChange={(value) => value && updateTopic(value)}
                            options={feedbackTopics.map((topic) => ({
                                label: topic.name,
                                value: topic.id,
                            }))}
                            size="small"
                            placeholder="Select topic"
                        />
                    }
                />

                <MetadataRow
                    title="Assigned to"
                    value={
                        <MemberSelect
                            value={feedbackItem.assignment?.user?.id ?? null}
                            onChange={(user) => updateAssignment(user?.id ?? null)}
                            defaultLabel="Unassigned"
                            allowNone={true}
                            type="secondary"
                            size="small"
                        />
                    }
                />
            </div>
        </div>
    )
}

interface MetadataRowProps {
    title: string
    value: React.ReactNode
    valueClassName?: string
}

function MetadataRow({ title, value, valueClassName }: MetadataRowProps): JSX.Element {
    return (
        <div className="p-4">
            <h4 className="text-xs font-semibold text-muted mb-2">{title}</h4>
            {typeof value === 'string' ? <p className={`text-sm m-0 ${valueClassName || ''}`}>{value}</p> : value}
        </div>
    )
}
